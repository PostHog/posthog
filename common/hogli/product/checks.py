"""Check framework and all product lint checks.

Lint checks are pass/fail structural correctness checks. They answer "is anything
broken?" — missing files, broken scripts, misplaced code.

Progress/maturity scoring lives in maturity.py instead.
"""

from __future__ import annotations

import re
import json
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .paths import TACH_TOML, get_tach_block
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
    warnings: list[str] = field(default_factory=list)  # non-blocking warnings
    file: str | None = None  # file path for GitHub annotations
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

        # --- presence checks (legacy leaks exempt from contract-check) ---
        from .ast_helpers import has_any_function_defs

        module_path = f"products.{ctx.name}"
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        has_leaks = has_legacy_interface_leaks(tach_content, module_path)

        facade_api = ctx.backend_dir / "facade" / "api.py"
        has_real_facade = facade_api.exists() and has_any_function_defs(facade_api)
        needs_contract_check = ctx.is_isolated and not has_leaks and has_real_facade
        required = ["backend:test"] + (["backend:contract-check"] if needs_contract_check else [])
        for script in required:
            if script not in scripts:
                result.lines.append(f"✗ missing '{script}'")
                result.issues.append(
                    f"Product has backend/ but package.json is missing '{script}' script — "
                    "turbo cannot discover this product"
                )

        # --- absence check: must NOT have contract-check when not safe for isolation ---
        must_not_have_contract_check = not ctx.is_isolated or has_leaks or not has_real_facade
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
        result.file = f"products/{ctx.name}/package.json"
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
        tach_block = get_tach_block(module_path)

        if not tach_block:
            return CheckResult(
                lines=["✗ missing from tach.toml"],
                issues=[
                    f"Product has Python files but no [[modules]] entry in tach.toml — "
                    f'add a block with path = "{module_path}"'
                ],
            )

        if ctx.is_isolated and "interfaces" not in tach_block:
            # Check global [[interfaces]] blocks — the product name may appear
            # literally or as part of a regex pattern in a from = [...] field.
            tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
            product_short = ctx.name
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

        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        if has_legacy_interface_leaks(tach_content, module_path):
            return CheckResult(lines=["⚠ has legacy interface leaks — core bypasses facade (not tested in isolation)"])

        return CheckResult(lines=["✓ ok"])


class IsolationChainCheck(ProductCheck):
    """Validates the isolation prerequisite chain is consistent.

    The chain: real facade → tach interfaces → contract-check script → narrowed turbo.json.
    Each step requires the previous one. A product that skips a step gets CI
    benefits it hasn't earned (Django suite skipped on changes).
    """

    label = "isolation chain"

    def _has_contract_check_script(self, product_dir: Path) -> bool:
        package_json = product_dir / "package.json"
        if not package_json.exists():
            return False
        try:
            scripts = json.loads(package_json.read_text()).get("scripts", {})
        except json.JSONDecodeError:
            return False
        return "backend:contract-check" in scripts

    def _has_narrowed_turbo_inputs(self, product_dir: Path) -> bool:
        turbo_json = product_dir / "turbo.json"
        if not turbo_json.exists():
            return False
        try:
            tasks = json.loads(turbo_json.read_text()).get("tasks", {})
        except json.JSONDecodeError:
            return False
        contract_task = tasks.get("backend:contract-check")
        if not contract_task:
            return False
        inputs = contract_task.get("inputs", [])
        return any("facade" in i or "presentation" in i for i in inputs)

    def _has_tach_interfaces(self, name: str) -> bool:
        module_path = f"products.{name}"
        block = get_tach_block(module_path)
        if not block:
            return False
        if "interfaces" in block and "interfaces = []" not in block:
            return True
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        return bool(
            re.search(
                rf"\[\[interfaces\]\].*?from\s*=\s*\[.*?{re.escape(name)}",
                tach_content,
                re.DOTALL,
            )
        )

    def run(self, ctx: CheckContext) -> CheckResult:
        from .ast_helpers import has_any_function_defs

        facade_api = ctx.backend_dir / "facade" / "api.py"
        has_real_facade = facade_api.exists() and has_any_function_defs(facade_api)
        has_tach = self._has_tach_interfaces(ctx.name)
        has_script = self._has_contract_check_script(ctx.product_dir)
        has_narrowed = self._has_narrowed_turbo_inputs(ctx.product_dir)

        result = CheckResult()

        if has_script and not has_real_facade:
            result.issues.append(
                "has 'backend:contract-check' but facade/api.py has no function definitions — "
                "re-exporting from logic is not a facade. turbo-discover classifies this product "
                "as isolated, which may cause the Django test suite to be skipped on changes"
            )

        if has_script and not has_tach:
            result.issues.append(
                "has 'backend:contract-check' but no tach interfaces — isolation requires tach boundary enforcement"
            )

        if has_narrowed and not has_script:
            result.issues.append(
                "turbo.json narrows contract-check inputs but package.json has no "
                "'backend:contract-check' script — dead config, remove the turbo.json override"
            )

        if has_narrowed and not has_real_facade:
            result.issues.append(
                "turbo.json narrows contract-check inputs to facade/presentation but "
                "facade/api.py has no function definitions — internal changes won't trigger "
                "Django suite even though the facade boundary isn't real"
            )

        if not has_script and facade_api.exists() and not has_real_facade:
            result.warnings.append(
                "facade/api.py exists but has no function definitions — "
                "a real facade should convert models to contracts, not just re-export"
            )

        if result.issues or result.warnings:
            result.file = f"products/{ctx.name}/backend/facade/api.py"
        if result.issues:
            result.lines = [f"✗ {len(result.issues)} issue(s)"] + [f"  → {i}" for i in result.issues]
        elif result.warnings:
            result.lines = [f"⚠ {len(result.warnings)} warning(s)"] + [f"  → {w}" for w in result.warnings]
        else:
            result.lines = ["✓ ok"]

        return result


class ProductYamlCheck(ProductCheck):
    """Validates product.yaml exists, parses, and has correct field types."""

    label = "product.yaml"

    def run(self, ctx: CheckContext) -> CheckResult:
        from .product_yaml import parse_product_yaml

        yaml_path = ctx.product_dir / "product.yaml"

        if not yaml_path.exists():
            return CheckResult(
                lines=["✗ missing"],
                issues=["Missing product.yaml — every product needs name and owners"],
                file=f"products/{ctx.name}",
            )

        result = CheckResult(file=f"products/{ctx.name}/product.yaml")

        data, parse_err = parse_product_yaml(yaml_path)
        if parse_err:
            result.issues.append(f"product.yaml {parse_err}")
            result.lines = [f"✗ {result.issues[0]}"]
            return result

        name = data.get("name")
        if not name or not isinstance(name, str):
            result.issues.append("product.yaml missing 'name' field (must be a non-empty string)")

        owners = data.get("owners")
        if not owners:
            result.issues.append("product.yaml missing 'owners' field — who owns this product?")
        elif not isinstance(owners, list) or not all(isinstance(o, str) for o in owners):
            result.issues.append("product.yaml 'owners' must be a list of strings")

        if result.issues:
            result.lines = [f"✗ {len(result.issues)} issue(s)"] + [f"  → {i}" for i in result.issues]
        else:
            result.lines = ["✓ ok"]
        return result


class ProductYamlOwnersCheck(ProductCheck):
    """Validates product.yaml owner slugs against GitHub org teams."""

    label = "product.yaml owners"

    def run(self, ctx: CheckContext) -> CheckResult:
        from .gh import get_team_slugs
        from .product_yaml import parse_product_yaml

        yaml_path = ctx.product_dir / "product.yaml"
        if not yaml_path.exists():
            return CheckResult(skip=True)

        data, parse_err = parse_product_yaml(yaml_path)
        if parse_err:
            return CheckResult(skip=True)

        owners = data.get("owners")
        if not owners or not isinstance(owners, list):
            return CheckResult(skip=True)

        gh_teams, fetch_err = get_team_slugs()
        if gh_teams is None:
            import os

            if os.environ.get("GITHUB_ACTIONS") == "true":
                return CheckResult(lines=[f"⚠ {fetch_err}, skipping in CI"])
            return CheckResult(
                lines=[f"✗ {fetch_err}"],
                issues=[fetch_err],
                file=f"products/{ctx.name}/product.yaml",
            )

        result = CheckResult(file=f"products/{ctx.name}/product.yaml")

        for owner in owners:
            if isinstance(owner, str) and owner not in gh_teams:
                result.issues.append(
                    f"owner '{owner}' is not a GitHub team in PostHog org — check https://github.com/orgs/PostHog/teams"
                )

        if result.issues:
            result.lines = [f"✗ {len(result.issues)} issue(s)"] + [f"  → {i}" for i in result.issues]
        else:
            result.lines = ["✓ ok"]
        return result


CHECKS: list[ProductCheck] = [
    ProductYamlCheck(),
    ProductYamlOwnersCheck(),
    RequiredRootFilesCheck(),
    PackageJsonScriptsCheck(),
    MisplacedFilesCheck(),
    FileFolderConflictsCheck(),
    TachCheck(),
    IsolationChainCheck(),
]
