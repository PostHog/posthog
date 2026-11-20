import re
import ast
import json
from pathlib import Path

# Generated configs are watched per module, because watching the package re-runs the Django
# suite for every source. This test holds that list to what the watched files refer to.

_INPUTS_PREFIX = "backend/temporal/data_imports/sources/"
_GENERATED_CONFIGS_DIR = f"{_INPUTS_PREFIX}generated_configs/"
_GENERATED_CONFIG_REFERENCE = re.compile(r"(?:[\w.]+\.)?sources\.generated_configs(?:\.(\w+))?(?:\.[\w.]+)?")


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".depot" / "workflows" / "ci-backend.yml").exists():
            return parent
    raise RuntimeError("repo root not found")


def _contract_check_inputs(root: Path) -> list[str] | None:
    turbo_path = root / "products" / "warehouse_sources" / "turbo.json"
    if not turbo_path.exists():
        return None
    turbo = json.loads(turbo_path.read_text())
    return turbo.get("tasks", {}).get("backend:contract-check", {}).get("inputs") or None


def _is_watched(rel: Path, inputs: list[str]) -> bool:
    included = any(rel.full_match(glob) for glob in inputs if not glob.startswith("!"))
    excluded = any(rel.full_match(glob.removeprefix("!")) for glob in inputs if glob.startswith("!"))
    return included and not excluded


def _referenced_generated_configs(tree: ast.AST, config_modules: set[str]) -> set[str]:
    dotted: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.ImportFrom(module=str(module), names=names):
                dotted |= {module, *(f"{module}.{alias.name}" for alias in names)}
            case ast.Import(names=names):
                dotted |= {alias.name for alias in names}
            case ast.Constant(value=str(value)):
                dotted.add(value)
    # A name under the package that is not a config module comes from the hand-written __init__.
    return {
        match[1] if match[1] in config_modules else "__init__"
        for path in dotted
        if (match := _GENERATED_CONFIG_REFERENCE.fullmatch(path))
    }


def test_contract_check_watches_exactly_the_generated_configs_it_refers_to() -> None:
    root = _repo_root()
    product_dir = root / "products" / "warehouse_sources"
    configs_dir = product_dir / _GENERATED_CONFIGS_DIR
    inputs = _contract_check_inputs(root)
    if inputs is None or f"{_GENERATED_CONFIGS_DIR}**" in inputs:
        return

    config_modules = {file.stem for file in configs_dir.glob("*.py")}
    referenced: set[str] = set()
    for file in (product_dir / "backend").rglob("*.py"):
        if _is_watched(file.relative_to(product_dir), inputs) and not file.is_relative_to(configs_dir):
            referenced |= _referenced_generated_configs(ast.parse(file.read_text(), filename=str(file)), config_modules)

    watched = {Path(glob).stem for glob in inputs if glob.startswith(_GENERATED_CONFIGS_DIR)}
    assert watched == referenced, (
        "products/warehouse_sources/turbo.json backend:contract-check inputs must list exactly the "
        "generated configs the watched files refer to"
    )
