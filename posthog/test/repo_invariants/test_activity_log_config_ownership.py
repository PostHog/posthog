"""A scope's activity-log tuning is registered once, and owned by the team that owns its model.

Tuning lives next to the model in a data-only module (`activity_log_config.py`) which
`posthog/models/activity_logging/activity_log.py` merges. The guard catches misplaced or unloaded
configs because they can silently change reviews or activity-log output.
"""

import os
import inspect
from pathlib import Path
from typing import Any

from django.apps import apps
from django.test import SimpleTestCase

from owners_yaml import OwnersResolver

from posthog.models.activity_logging.activity_log import _SCOPE_CONFIG_MODULES

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_ATTRIBUTES = (
    "FIELD_EXCLUSIONS",
    "FIELD_NAME_OVERRIDES",
    "FIELD_WITH_MASKED_CONTENTS",
    "SIGNAL_EXCLUSIONS",
)
# Scan broadly to catch misplaced product configs as well as configs beside core models.
# The skipped directories hold copies of the repository, not code that ships.
TUNING_TREES = ("posthog", "products", "ee")
SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".turbo", ".next", ".pytest_cache"}


def _repo_path(obj: Any) -> str:
    return Path(inspect.getfile(obj)).resolve().relative_to(REPO_ROOT).as_posix()


def _tuning_modules_in_tree() -> set[str]:
    found: set[str] = set()
    for tree in TUNING_TREES:
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT / tree):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                if filename.endswith("activity_log_config.py"):
                    found.add((Path(dirpath) / filename).relative_to(REPO_ROOT).as_posix())
    return found


class TestActivityLogConfigOwnership(SimpleTestCase):
    def test_every_config_module_in_the_tree_is_loaded(self) -> None:
        loaded = {_repo_path(module) for module in _SCOPE_CONFIG_MODULES}
        in_tree = _tuning_modules_in_tree()
        for config_path in sorted(loaded | in_tree):
            parts = Path(config_path).parts
            if parts[0] == "products":
                assert len(parts) == 4 and parts[2:] == ("backend", "activity_log_config.py"), (
                    f"{config_path}: product configs must use products/<name>/backend/activity_log_config.py "
                    'so load_product_modules("activity_log_config") can discover them.'
                )

        assert loaded == in_tree, (
            f"Unloaded tuning modules: {sorted(in_tree - loaded)}. "
            "Product configs load from installed apps. Add core configs to "
            "_SCOPE_CONFIG_MODULES in posthog/models/activity_logging/activity_log.py. "
            f"Loaded modules outside the scanned config paths: {sorted(loaded - in_tree)}."
        )

    def test_config_modules_only_define_known_settings(self) -> None:
        for module in _SCOPE_CONFIG_MODULES:
            unknown = {name for name in vars(module) if name.isupper()} - set(CONFIG_ATTRIBUTES)
            assert not unknown, (
                f"{_repo_path(module)}: unknown activity-log settings {sorted(unknown)}. "
                f"Use only {', '.join(CONFIG_ATTRIBUTES)}; misspelled settings silently drop tuning."
            )

    def test_a_scope_is_tuned_by_the_team_that_owns_its_model(self) -> None:
        resolver = OwnersResolver(repo_root=REPO_ROOT)
        model_by_scope = {model.__name__: model for model in apps.get_models()}
        checked = 0

        for module in _SCOPE_CONFIG_MODULES:
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
