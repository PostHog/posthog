"""Check framework and all product lint checks."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .ast_helpers import (
    contract_coverage,
    count_direct_orm_queries,
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

        required = ["backend:test"] + (["backend:contract-check"] if ctx.is_isolated else [])
        result = CheckResult()
        for script in required:
            if script not in scripts:
                result.lines.append(f"✗ missing '{script}'")
                result.issues.append(
                    f"Product has backend/ but package.json is missing '{script}' script — "
                    "turbo cannot discover this product"
                )
        if not result.issues:
            result.lines.append("✓ ok")
        return result


class MisplacedFilesCheck(ProductCheck):
    label = "misplaced backend files"
    for_lenient = False

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


class TachInterfacesCheck(ProductCheck):
    label = "tach interfaces"
    for_lenient = False

    def run(self, ctx: CheckContext) -> CheckResult:
        module_path = f"products.{ctx.name}"
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
        if "interfaces" not in get_tach_block(tach_content, module_path):
            return CheckResult(
                lines=["✗ missing interfaces declaration"],
                issues=[
                    f"Isolated product missing 'interfaces' in tach.toml — "
                    f'add interfaces = ["{module_path}.backend.facade", '
                    f'"{module_path}.backend.presentation.views"]'
                ],
            )
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

        if ctx.detailed and model_names:
            result.lines.append(f"models ({n}): {', '.join(model_names)}")
        else:
            result.lines.append(f"models: {n} to cover")

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
        else:
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
        else:
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

        # Views
        views_path = ctx.backend_dir / "presentation" / "views.py"
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
                    issues_parts.append(f"{orm_queries} direct ORM quer{'y' if orm_queries == 1 else 'ies'}")
                result.lines.append(f"views:      ~ uses facade but {', '.join(issues_parts)}")
                if hint := self._hint(
                    ctx, "route all data access through the facade — remove model imports and .objects. calls"
                ):
                    result.lines.append(hint)
            else:
                suffix = f" ({orm_queries} direct ORM quer{'y' if orm_queries == 1 else 'ies'})" if orm_queries else ""
                result.lines.append(f"views:      ✗ no facade usage{suffix}")
                if hint := self._hint(ctx, "update views to call facade methods instead of querying models directly"):
                    result.lines.append(hint)
        else:
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
    TachInterfacesCheck(),
    IsolationProgressCheck(),
]
