"""A scope's activity-log tuning is registered once, and owned by the team that owns its model.

Tuning lives next to the model in a data-only module (`activity_log_config.py`) which
`posthog/models/activity_logging/activity_log.py` merges. That placement is what gives the owning
product team review rights over its own diff config, so a module dropped into another team's tree
would silently hand those rights to the wrong people.

Registering a module in `activity_log_config_registry.py` is mechanical, so that file is deliberately
unowned and a product adding one needs no review from the activity log's owners. This guard is what
makes that safe.
"""

import os
import types
import inspect
from pathlib import Path
from typing import Any

from django.apps import apps
from django.test import SimpleTestCase

from owners_yaml import OwnersResolver

from posthog.models.activity_logging import activity_log, activity_log_config_registry

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_ATTRIBUTES = (
    "FIELD_EXCLUSIONS",
    "FIELD_NAME_OVERRIDES",
    "FIELD_WITH_MASKED_CONTENTS",
    "SIGNAL_EXCLUSIONS",
)
# A tuning module may sit anywhere in these trees, including beside a model in a core subdirectory,
# so the guard walks them rather than globbing one level. The skipped directories hold copies of the
# repository, not code that ships.
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
    def test_every_config_module_in_the_tree_is_registered(self) -> None:
        registered = {_repo_path(module) for module in activity_log_config_registry.MODULES}
        in_tree = _tuning_modules_in_tree()
        assert registered == in_tree, (
            f"A tuning module is not registered: {sorted(in_tree - registered)}. Import it in "
            "posthog/models/activity_logging/activity_log_config_registry.py and add it to MODULES."
        )

    def test_the_registry_file_is_unowned(self) -> None:
        registry_path = _repo_path(activity_log_config_registry)
        resolution = OwnersResolver(repo_root=REPO_ROOT).resolve(registry_path)
        assert resolution.unowned_by_design, (
            f"{registry_path} resolves to {resolution.owners}. Mark it `owners: null` in "
            "posthog/models/owners.yaml: a product registering its own tuning must not need that team's review."
        )

    def test_a_scope_is_tuned_by_the_team_that_owns_its_model(self) -> None:
        resolver = OwnersResolver(repo_root=REPO_ROOT)
        model_by_scope = {model.__name__: model for model in apps.get_models()}
        checked = 0

        for module in activity_log_config_registry.MODULES:
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


class TestScopeConfigMerging(SimpleTestCase):
    """One scope is tuned in exactly one place, and the merge is what enforces it.

    Each case drives the merge with its own registries, because the real ones are filled when the
    module is imported: deleting the check would otherwise let the later definition silently replace
    the earlier one.
    """

    def test_two_modules_tuning_the_same_scope_raise(self) -> None:
        first = types.SimpleNamespace(__name__="first", FIELD_EXCLUSIONS={"Thing": ["a"]})
        second = types.SimpleNamespace(__name__="second", FIELD_EXCLUSIONS={"Thing": ["b"]})

        with self.assertRaisesMessage(RuntimeError, "Thing is tuned twice"):
            activity_log._merge_scope_configs({"FIELD_EXCLUSIONS": {}}, (first, second))

    def test_a_scope_tuned_in_core_and_in_a_module_raises(self) -> None:
        module = types.SimpleNamespace(__name__="module", FIELD_EXCLUSIONS={"Thing": ["b"]})

        with self.assertRaisesMessage(RuntimeError, "Thing is tuned twice"):
            activity_log._merge_scope_configs({"FIELD_EXCLUSIONS": {"Thing": ["core"]}}, (module,))
