"""A scope's activity-log tuning is owned by the team that owns the model it tunes.

Tuning lives next to the model in a data-only module (`activity_log_config.py`) which
`posthog/models/activity_logging/activity_log.py` merges. That placement is what gives the owning
product team review rights over its own diff config, so a module dropped into another team's tree
would silently hand those rights to the wrong people.
"""

import inspect
from pathlib import Path
from typing import Any

from django.apps import apps
from django.test import SimpleTestCase

from owners_yaml import OwnersResolver

from posthog.models.activity_logging import activity_log

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_ATTRIBUTES = (
    "FIELD_EXCLUSIONS",
    "FIELD_NAME_OVERRIDES",
    "FIELD_WITH_MASKED_CONTENTS",
    "SIGNAL_EXCLUSIONS",
)
# The two locations a config module is allowed to take: an app's package, where discovery finds it,
# and a core model's directory, where it is registered explicitly in `activity_log.py`.
CONFIG_FILE_GLOBS = ("products/*/backend/activity_log_config.py", "posthog/models/*activity_log_config.py")


def _repo_path(obj: Any) -> str:
    return Path(inspect.getfile(obj)).resolve().relative_to(REPO_ROOT).as_posix()


class TestActivityLogConfigOwnership(SimpleTestCase):
    def test_every_config_file_in_the_tree_is_merged(self) -> None:
        merged = {_repo_path(module) for module in activity_log.scope_config_modules()}
        tree_files = {
            path.relative_to(REPO_ROOT).as_posix() for glob in CONFIG_FILE_GLOBS for path in REPO_ROOT.glob(glob)
        }
        assert merged == tree_files, (
            f"A config module is not merged: {sorted(tree_files - merged)}. Name it "
            "`<app>.activity_log_config` so discovery finds it, or register it in "
            "`_SCOPE_CONFIG_MODULES` when it tunes a core model, but not both."
        )

    def test_a_scope_is_tuned_by_the_team_that_owns_its_model(self) -> None:
        resolver = OwnersResolver(repo_root=REPO_ROOT)
        model_by_scope = {model.__name__: model for model in apps.get_models()}
        checked = 0

        for module in activity_log.scope_config_modules():
            config_path = _repo_path(module)
            config_owners = set(resolver.resolve(config_path).owners or [])
            assert config_owners, f"{config_path} has no owner, so nobody reviews its tuning"

            for attribute in CONFIG_ATTRIBUTES:
                for scope in getattr(module, attribute, {}):
                    model = model_by_scope.get(scope)
                    assert model is not None, (
                        f"{config_path} tunes {scope}, which is not a model. A per-scope config module "
                        "follows the owner of its model, so a scope that is not a model stays in "
                        "posthog/models/activity_logging/activity_log.py."
                    )
                    model_path = _repo_path(model)
                    model_owners = set(resolver.resolve(model_path).owners or [])
                    assert config_owners & model_owners, (
                        f"{config_path} tunes {scope}, but {model_path} belongs to "
                        f"{sorted(model_owners) or 'nobody'} and the module belongs to {sorted(config_owners)}."
                    )
                    checked += 1

        assert checked, "no migrated activity-log config to check, so this guard is not wired up"
