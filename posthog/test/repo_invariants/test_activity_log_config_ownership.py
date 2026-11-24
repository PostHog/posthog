"""A scope's activity-log tuning is registered once, and owned by the team that owns its model.

Tuning lives next to the model in a data-only module (`activity_log_config.py`) which
`posthog/models/activity_logging/activity_log.py` merges. The guard catches misplaced or unloaded
configs because they can silently change reviews or activity-log output.
"""

import os
import ast
import inspect
from pathlib import Path
from typing import Any

from django.apps import apps
from django.test import SimpleTestCase

from owners_yaml import OwnersResolver

from posthog.models.activity_logging import activity_log_config_registry
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
    def test_the_registry_contains_only_imports_and_modules(self) -> None:
        registry_path = REPO_ROOT / "posthog/models/activity_logging/activity_log_config_registry.py"
        tree = ast.parse(registry_path.read_text(), filename=str(registry_path))
        statements = tree.body[1:] if ast.get_docstring(tree) is not None else tree.body
        assignments = 0

        for statement in statements:
            with self.subTest(line=statement.lineno):
                if isinstance(statement, (ast.Import, ast.ImportFrom)):
                    continue

                assert isinstance(statement, (ast.Assign, ast.AnnAssign)), (
                    f"{registry_path}:{statement.lineno}: only imports and the MODULES assignment are allowed. "
                    "Put logic in activity_log.py so its owners review it."
                )
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                assert len(targets) == 1 and isinstance(targets[0], ast.Name) and targets[0].id == "MODULES", (
                    f"{registry_path}:{statement.lineno}: MODULES must be the only assignment target."
                )
                assert isinstance(statement.value, ast.Tuple) and all(
                    isinstance(element, ast.Name) for element in statement.value.elts
                ), f"{registry_path}:{statement.lineno}: MODULES must be a tuple of imported module names."
                if isinstance(statement, ast.AnnAssign):
                    assert all(
                        isinstance(node, (ast.Name, ast.Subscript, ast.Tuple, ast.Constant, ast.Load))
                        for node in ast.walk(statement.annotation)
                    ), f"{registry_path}:{statement.lineno}: the MODULES annotation must not contain logic."
                assignments += 1

        assert assignments == 1, f"{registry_path}: expected exactly one MODULES assignment, found {assignments}."

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
            "MODULES in posthog/models/activity_logging/activity_log_config_registry.py. "
            f"Loaded modules outside the scanned config paths: {sorted(loaded - in_tree)}."
        )

    def test_config_modules_only_define_known_settings(self) -> None:
        for module in _SCOPE_CONFIG_MODULES:
            unknown = {name for name in vars(module) if name.isupper()} - set(CONFIG_ATTRIBUTES)
            assert not unknown, (
                f"{_repo_path(module)}: unknown activity-log settings {sorted(unknown)}. "
                f"Use only {', '.join(CONFIG_ATTRIBUTES)}; misspelled settings silently drop tuning."
            )

    def test_the_registry_file_is_unowned(self) -> None:
        registry_path = _repo_path(activity_log_config_registry)
        resolution = OwnersResolver(repo_root=REPO_ROOT).resolve(registry_path)
        assert resolution.unowned_by_design, (
            f"{registry_path} resolves to {resolution.owners}. Mark it `owners: null` in "
            "posthog/models/owners.yaml: a model team registering its own tuning must not need that team's review."
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
