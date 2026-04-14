"""Check framework and all product lint checks."""

from __future__ import annotations

import json
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .ast_helpers import (
    contract_coverage,
    count_direct_orm_queries,
    count_viewset_files,
    get_cross_product_internal_imports,
    get_frozen_dataclass_names,
    get_model_names,
    get_orm_bound_serializer_names,
    get_public_function_names,
    imports_any,
    view_facade_usage,
)
from .paths import TACH_TOML
from .scaffold import flatten_structure

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def check_file_exists(backend_dir: Path, path: str) -> bool:
    """Check if a file or its folder equivalent exists."""
    file_path = backend_dir / path
    if file_path.exists():
        return True
    if path.endswith(".py"):
        folder_path = backend_dir / path.replace(".py", "")
        if folder_path.exists() and folder_path.is_dir():
            return True
    return False


def has_legacy_interface_leaks(tach_content: str, module_path: str) -> bool:
    """Check if a product has legacy interface leak blocks in tach.toml.

    These are products where core (posthog/ee) still imports internals directly,
    so they can't safely be tested in isolation via contract-check.

    Detected structurally: an [[interfaces]] block that exposes non-facade paths
    (anything other than backend.facade or backend.presentation) and references
    this specific module in its from = [...] field.
    """
    import re

    # Find all [[interfaces]] blocks and check if any expose non-facade paths
    # for this specific module.
    for match in re.finditer(r"\[\[interfaces\]\]\s*\n(.*?)(?=\[\[|\Z)", tach_content, re.DOTALL):
        block = match.group(1)
        # Check if this block references our module in from = [...]
        if not re.search(rf'from\s*=\s*\[\s*"{re.escape(module_path)}"\s*,?\s*\]', block):
            continue
        # Check if any expose pattern is NOT facade or presentation
        expose_match = re.search(r"expose\s*=\s*\[(.*?)\]", block, re.DOTALL)
        if not expose_match:
            continue
        patterns = re.findall(r'"(.*?)"', expose_match.group(1))
        for pattern in patterns:
            if not pattern.startswith("backend\\.facade") and not pattern.startswith("backend\\.presentation"):
                return True
    return False


def get_tach_block(tach_content: str, module_path: str) -> str:
    """Extract the tach.toml block for a given module path."""
    marker = f'path = "{module_path}"'
    idx = tach_content.find(marker)
    if idx == -1:
        return ""
    block_start = tach_content.rfind("[[modules]]", 0, idx)
    if block_start == -1:
        block_start = idx
    next_block = tach_content.find("[[modules]]", idx)
    if next_block == -1:
        return tach_content[block_start:]
    return tach_content[block_start:next_block]


def is_isolated_product(backend_dir: Path) -> bool:
    return (backend_dir / "facade" / "contracts.py").exists() or (backend_dir / "facade" / "contracts").exists()


# ---------------------------------------------------------------------------
# Check framework
# ---------------------------------------------------------------------------


@dataclass
class CheckContext:
    name: str
    product_dir: Path
    backend_dir: Path
    is_isolated: bool
    structure: dict
    detailed: bool  # True = single-product run, False = --all


@dataclass
class CheckResult:
    lines: list[str] = field(default_factory=list)  # lines printed to stdout
    issues: list[str] = field(default_factory=list)  # blocking issues returned to caller
    skip: bool = False  # silently skip this check


class ProductCheck(ABC):
    label: str
    for_isolated: bool = True
    for_lenient: bool = True

    def should_run(self, ctx: CheckContext) -> bool:
        if ctx.is_isolated and not self.for_isolated:
            return False
        if not ctx.is_isolated and not self.for_lenient:
            return False
        return True

    @abstractmethod
    def run(self, ctx: CheckContext) -> CheckResult: ...


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


class RequiredRootFilesCheck(ProductCheck):
    label = "required root files"

    def run(self, ctx: CheckContext) -> CheckResult:
        required_key = "required" if ctx.is_isolated else "required_lenient"
        missing = [
            filename
            for filename, config in ctx.structure.get("root_files", {}).items()
            if config.get(required_key, False) and not (ctx.product_dir / filename).exists()
        ]
        if missing:
            return CheckResult(
                lines=[f"✗ missing: {', '.join(missing)}"],
                issues=[f"Missing required root file: {f}" for f in missing],
            )
        return CheckResult(lines=["✓ ok"])


def _has_test_files(backend_dir: Path) -> bool:
    """Check if backend/ contains any pytest-discoverable test files."""
    return any(backend_dir.rglob("test_*.py")) or any(backend_dir.rglob("*_test.py"))


def _is_noop_script(script: str) -> bool:
    """Check if a script is a no-op (echo, true, exit 0, etc.)."""
    stripped = script.strip()
    return stripped.startswith("echo ") or stripped in ("true", "exit 0", ":")


def _parse_pytest_paths(script: str) -> list[str]:
    """Extract test path arguments from a pytest command.

    Given something like:
        pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short
    Returns:
        ["backend/tests"]
    """
    try:
        parts = shlex.split(script)
    except ValueError:
        parts = script.split()
    if not parts or parts[0] != "pytest":
        return []

    paths: list[str] = []
    skip_next = False
    for part in parts[1:]:
        if skip_next:
            skip_next = False
            continue
        # flags that consume the next token
        if part in ("-c", "--rootdir", "-k", "-m", "-p", "--override-ini", "-o"):
            skip_next = True
            continue
        # skip flags
        if part.startswith("-"):
            continue
        paths.append(part)
    return paths


class PackageJsonScriptsCheck(ProductCheck):
    label = "package.json scripts"

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        package_json = ctx.product_dir / "package.json"
        try:
            scripts = json.loads(package_json.read_text()).get("scripts", {}) if package_json.exists() else {}
        except json.JSONDecodeError:
            return CheckResult(
                lines=["✗ package.json is not valid JSON"],
                issues=["package.json is not valid JSON"],
            )

        result = CheckResult()

        # --- presence checks ---
        module_path = f"products.{ctx.name}"
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        has_leaks = has_legacy_interface_leaks(tach_content, module_path)

        needs_contract_check = ctx.is_isolated and not has_leaks
        required = ["backend:test"] + (["backend:contract-check"] if needs_contract_check else [])
        for script in required:
            if script not in scripts:
                result.lines.append(f"✗ missing '{script}'")
                result.issues.append(
                    f"Product has backend/ but package.json is missing '{script}' script — "
                    "turbo cannot discover this product"
                )

        # --- absence check: must NOT have contract-check when not safe for isolation ---
        must_not_have_contract_check = not ctx.is_isolated or has_leaks
        if must_not_have_contract_check and "backend:contract-check" in scripts:
            if has_leaks:
                reason = "has legacy interface leaks (core imports internals directly)"
            else:
                reason = "non-isolated product must not have 'backend:contract-check' script"
            result.lines.append("✗ must not have 'backend:contract-check'")
            result.issues.append(
                f"{reason} — remove 'backend:contract-check' from package.json. "
                "turbo-discover uses this to classify products as isolated, which causes "
                "the full Django test suite to be skipped when this product changes"
            )

        # --- content checks on backend:test ---
        test_script = scripts.get("backend:test", "")
        if test_script:
            # strip trailing || true / || exit 0 before further checks
            base_script = test_script.split("||")[0].strip()

            # check: || true / || exit 0 swallows failures
            if "||" in test_script:
                tail = test_script.split("||", 1)[1].strip()
                if tail in ("true", "exit 0"):
                    result.lines.append(f"✗ 'backend:test' uses '|| {tail}'")
                    result.issues.append(f"'backend:test' script uses '|| {tail}' which swallows test failures in CI")

            # check: no-op script but test files exist
            if _is_noop_script(base_script) and _has_test_files(ctx.backend_dir):
                result.lines.append("✗ 'backend:test' is a no-op but test files exist")
                result.issues.append(
                    "'backend:test' is a no-op (e.g. echo) but backend/ contains test files "
                    "that will never run — update the script to use pytest"
                )

            # check: pytest paths exist on disk
            if base_script.startswith("pytest"):
                test_paths = _parse_pytest_paths(base_script)
                for tp in test_paths:
                    resolved = ctx.product_dir / tp
                    if not resolved.exists():
                        result.lines.append(f"✗ test path '{tp}' does not exist")
                        result.issues.append(
                            f"'backend:test' references path '{tp}' which does not exist — "
                            "pytest will fail or silently collect zero tests"
                        )

        if not result.issues:
            result.lines.append("✓ ok")
        return result


class MisplacedFilesCheck(ProductCheck):
    label = "misplaced backend files"
    for_lenient = False

    # Directories allowed in backend/ for strict products.
    # Anything else won't be covered by import-linter's wildcard contracts.
    _KNOWN_DIRS = {
        "facade",
        "presentation",
        "tasks",
        "tests",
        "test",
        "migrations",
        "management",
        "models",
        "logic",
        "__pycache__",
    }

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        misplaced = []
        for filename, correct_path in ctx.structure.get("backend_known_files", {}).items():
            wrong = ctx.backend_dir / filename
            correct = ctx.backend_dir / correct_path
            if wrong.exists() and wrong.is_file():
                if correct.exists():
                    misplaced.append(f"'{filename}' at backend/ root conflicts with correct location '{correct_path}'")
                else:
                    misplaced.append(f"backend/{filename} should be at backend/{correct_path}")

        # Flag directories not in the canonical structure — these bypass
        # import-linter's wildcard enforcement (presentation/facade/etc.)
        for child in sorted(ctx.backend_dir.iterdir()):
            if child.is_dir() and child.name not in self._KNOWN_DIRS:
                misplaced.append(
                    f"backend/{child.name}/ is not a recognized directory — "
                    "import-linter only enforces canonical paths (presentation, facade, logic, models). "
                    "Move code into an existing directory or update the product structure"
                )

        if misplaced:
            return CheckResult(
                lines=[f"✗ {len(misplaced)} misplaced file(s)"] + [f"  → {m}" for m in misplaced],
                issues=misplaced,
            )
        return CheckResult(lines=["✓ ok"])


class FileFolderConflictsCheck(ProductCheck):
    label = "file/folder conflicts"

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        conflicts = []
        for path, config in flatten_structure(ctx.structure.get("backend_files", {})).items():
            if not config.get("can_be_folder", False):
                continue
            if (ctx.backend_dir / path).exists() and (ctx.backend_dir / path.replace(".py", "")).exists():
                conflicts.append(f"Both 'backend/{path}' and 'backend/{path.replace('.py', '/')}' exist — pick one")

        if conflicts:
            return CheckResult(
                lines=[f"✗ {len(conflicts)} conflict(s)"] + [f"  → {c}" for c in conflicts],
                issues=conflicts,
            )
        return CheckResult(lines=["✓ ok"])


class TachCheck(ProductCheck):
    label = "tach boundaries"

    def _has_python_files(self, product_dir: Path) -> bool:
        return any(p for p in product_dir.rglob("*.py") if p.name != "__init__.py")

    def run(self, ctx: CheckContext) -> CheckResult:
        if not self._has_python_files(ctx.product_dir):
            return CheckResult(skip=True)

        module_path = f"products.{ctx.name}"
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        tach_block = get_tach_block(tach_content, module_path)

        if not tach_block:
            return CheckResult(
                lines=["✗ missing from tach.toml"],
                issues=[
                    f"Product has Python files but no [[modules]] entry in tach.toml — "
                    f'add a block with path = "{module_path}"'
                ],
            )

        if ctx.is_isolated and "interfaces" not in tach_block:
            import re

            # Check global [[interfaces]] blocks — the product name may appear
            # literally or as part of a regex pattern in a from = [...] field.
            product_short = ctx.name  # e.g. "experiments"
            has_global_interface = bool(
                re.search(
                    rf"\[\[interfaces\]\].*?from\s*=\s*\[.*?{re.escape(product_short)}",
                    tach_content,
                    re.DOTALL,
                )
            )
            if not has_global_interface:
                return CheckResult(
                    lines=["✗ missing interfaces declaration"],
                    issues=[
                        f"Isolated product missing interface definition in tach.toml — "
                        f'add a [[interfaces]] block with from = ["{module_path}"]'
                    ],
                )

        tach_content_for_leaks = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        if has_legacy_interface_leaks(tach_content_for_leaks, module_path):
            return CheckResult(lines=["⚠ has legacy interface leaks — core bypasses facade (not tested in isolation)"])

        return CheckResult(lines=["✓ ok"])


class IsolationProgressCheck(ProductCheck):
    label = "isolation progress"
    for_isolated = False

    def _hint(self, ctx: CheckContext, text: str) -> str | None:
        return f"            → {text}" if ctx.detailed else None

    def run(self, ctx: CheckContext) -> CheckResult:
        if not ctx.backend_dir.exists():
            return CheckResult(skip=True)

        result = CheckResult()
        model_names = get_model_names(ctx.backend_dir)
        n = len(model_names)

        # Check if any view file exists (canonical or legacy locations)
        api_dir = ctx.backend_dir / "api"
        has_any_views = (
            (ctx.backend_dir / "presentation" / "views.py").exists()
            or (api_dir.is_dir() and count_viewset_files(api_dir) > 0)
            or (ctx.backend_dir / "api" / "views.py").exists()
            or (ctx.backend_dir / "api.py").exists()
            or (ctx.backend_dir / "views.py").exists()
        )

        if n == 0 and not has_any_views:
            result.lines.append("no Django models or views found — nothing to isolate yet")
            return result

        if ctx.detailed and model_names:
            result.lines.append(f"models ({n}): {', '.join(model_names)}")
        elif n > 0:
            result.lines.append(f"models: {n} to cover")
        else:
            result.lines.append("models: none in backend/ (may live in posthog/)")

        # logic.py
        has_logic = (ctx.backend_dir / "logic.py").exists() or (ctx.backend_dir / "logic").is_dir()
        if has_logic:
            result.lines.append("logic.py:   ✓ present")
        elif n > 0:
            result.lines.append("logic.py:   ○ missing")
            if hint := self._hint(
                ctx, "create backend/logic.py — business logic must not live in views or serializers"
            ):
                result.lines.append(hint)

        # Contracts layer
        contracts_path = ctx.backend_dir / "facade" / "contracts.py"
        if contracts_path.exists():
            dc_names = get_frozen_dataclass_names(contracts_path)
            impure = imports_any(contracts_path, ["django", "rest_framework"])
            covered, uncovered = contract_coverage(model_names, dc_names)
            coverage = f"{len(covered)}/{n} models covered" if n else f"{len(dc_names)} dataclass(es)"
            purity = " ✗ impure (django/drf imports)" if impure else ", pure"
            result.lines.append(f"contracts:  ✓ {coverage}{purity}")
            if ctx.detailed:
                if covered:
                    result.lines.append(f"            covered:   {', '.join(covered)}")
                if uncovered:
                    result.lines.append(f"            missing:   {', '.join(uncovered)}")
                    if hint := self._hint(ctx, f"add frozen dataclasses for: {', '.join(uncovered)}"):
                        result.lines.append(hint)
            if impure and (
                hint := self._hint(ctx, "remove django/rest_framework imports — contracts.py must be pure stdlib")
            ):
                result.lines.append(hint)
        elif n > 0:
            result.lines.append("contracts:  ○ missing")
            if hint := self._hint(
                ctx, "create backend/facade/contracts.py with @dataclass(frozen=True) for each model"
            ):
                result.lines.append(hint)

        # Facade layer
        facade_path = ctx.backend_dir / "facade" / "api.py"
        if facade_path.exists():
            fn_names = get_public_function_names(facade_path)
            impure = imports_any(facade_path, ["rest_framework"])
            purity = " ✗ impure (drf imports)" if impure else ", pure"
            result.lines.append(f"facade:     ✓ {len(fn_names)} public method(s){purity}")
            if ctx.detailed and fn_names:
                result.lines.append(f"            {', '.join(fn_names)}")
            if impure and (hint := self._hint(ctx, "remove rest_framework imports — facade must not depend on DRF")):
                result.lines.append(hint)
        elif n > 0:
            result.lines.append("facade:     ○ missing")
            if hint := self._hint(
                ctx, "create backend/facade/api.py with thin methods wrapping logic.py, returning contracts"
            ):
                result.lines.append(hint)

        # Serializers
        serializers_path = ctx.backend_dir / "presentation" / "serializers.py"
        if not serializers_path.exists():
            # also check legacy api/ location
            serializers_path = ctx.backend_dir / "api" / "serializers.py"
        if serializers_path.exists():
            orm_bound = get_orm_bound_serializer_names(serializers_path)
            if orm_bound:
                result.lines.append(f"serializers: ✗ {len(orm_bound)} ORM-bound (Meta.model)")
                if ctx.detailed:
                    result.lines.append(f"            {', '.join(orm_bound)}")
                    if hint := self._hint(
                        ctx, "rework these serializers to accept/return contracts instead of ORM models"
                    ):
                        result.lines.append(hint)
            else:
                result.lines.append("serializers: ✓ no ORM model bindings")

        # Views — check canonical location first, then legacy locations
        _LEGACY_VIEW_CANDIDATES = [
            ("api", "backend/api/"),  # package with multiple ViewSet files
            ("api/views.py", "backend/api/views.py"),
            ("api.py", "backend/api.py"),
            ("views.py", "backend/views.py"),
        ]
        views_path = ctx.backend_dir / "presentation" / "views.py"
        legacy_views: tuple[Path, str] | None = None
        if not views_path.exists():
            for rel, label in _LEGACY_VIEW_CANDIDATES:
                candidate = ctx.backend_dir / rel
                if candidate.is_dir() and count_viewset_files(candidate) > 0:
                    legacy_views = (candidate, label)
                    break
                elif candidate.is_file():
                    legacy_views = (candidate, label)
                    break

        if views_path.exists():
            uses_facade, uses_models = view_facade_usage(views_path)
            orm_queries = count_direct_orm_queries(views_path)
            if uses_facade and not uses_models and orm_queries == 0:
                result.lines.append("views:      ✓ uses facade, no direct ORM access")
            elif uses_facade:
                issues_parts = []
                if uses_models:
                    issues_parts.append("imports models directly")
                if orm_queries:
                    issues_parts.append(f"~{orm_queries} .objects call{'s' if orm_queries != 1 else ''}")
                result.lines.append(f"views:      ~ uses facade but {', '.join(issues_parts)}")
                if hint := self._hint(
                    ctx, "route all data access through the facade — remove model imports and .objects. calls"
                ):
                    result.lines.append(hint)
            else:
                suffix = f" (~{orm_queries} .objects call{'s' if orm_queries != 1 else ''})" if orm_queries else ""
                result.lines.append(f"views:      ✗ no facade usage{suffix}")
                if hint := self._hint(ctx, "update views to call facade methods instead of querying models directly"):
                    result.lines.append(hint)
        elif legacy_views:
            legacy_path, legacy_label = legacy_views
            uses_facade, uses_models = view_facade_usage(legacy_path)
            orm_queries = count_direct_orm_queries(legacy_path)
            parts = []
            if legacy_path.is_dir():
                vs_count = count_viewset_files(legacy_path)
                parts.append(f"{vs_count} ViewSet{'s' if vs_count != 1 else ''}")
            if uses_models:
                parts.append("imports models directly")
            if orm_queries:
                parts.append(f"~{orm_queries} .objects call{'s' if orm_queries != 1 else ''}")
            issues_str = f" — {', '.join(parts)}" if parts else ""
            result.lines.append(f"views:      ✗ at {legacy_label}{issues_str}")
            if hint := self._hint(ctx, "move to backend/presentation/views.py and route data access through facade"):
                result.lines.append(hint)
        else:
            if n > 0:
                result.lines.append("views:      ○ missing")
                if hint := self._hint(ctx, "create backend/presentation/views.py that calls facade methods only"):
                    result.lines.append(hint)

        # Cross-product internal imports (own files importing other products' non-facade paths)
        if ctx.detailed:
            violations = get_cross_product_internal_imports(ctx.product_dir, ctx.name)
            if violations:
                result.lines.append(f"cross-product: ✗ {len(violations)} non-facade import(s) from other products")
                for v in violations:
                    result.lines.append(f"               {v}")
                if hint := self._hint(ctx, "replace with imports from the other product's backend.facade"):
                    result.lines.append(hint)

        return result


CHECKS: list[ProductCheck] = [
    RequiredRootFilesCheck(),
    PackageJsonScriptsCheck(),
    MisplacedFilesCheck(),
    FileFolderConflictsCheck(),
    TachCheck(),
    IsolationProgressCheck(),
]
