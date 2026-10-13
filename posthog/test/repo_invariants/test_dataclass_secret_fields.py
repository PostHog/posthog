"""Ratchet guard for secret dataclass fields.

Dataclass fields whose names look like credentials (password, access_token,
api_key, ...) must be declared with field(repr=False) so the secret cannot
leak through repr() into tracebacks, logs, or pytest assertion diffs.
Fields that are legitimately not secrets go in the exemptions file.

Print the current violations (to fix them or to exempt a non-secret):

    python posthog/test/repo_invariants/test_dataclass_secret_fields.py
"""

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
EXEMPTIONS_PATH = Path(__file__).parent / "dataclass_secret_field_exemptions.txt"
SCANNED_ROOTS = ("posthog", "ee", "products", "dags", "common")
SKIPPED_DIRS = {"migrations", "test", "tests"}

SECRET_NAME_TOKENS = (
    "secret",
    "password",
    "passwd",
    "private_key",
    "access_token",
    "refresh_token",
    "id_token",
    "session_token",
    "sas_token",
    "api_key",
    "api_token",
    "client_assertion",
    "passphrase",
    "signing_key",
    "encryption_key",
)


def _dotted_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            base = _dotted_name(value)
            return f"{base}.{attr}" if base else None
        case _:
            return None


def _is_dataclass_decorator(decorator: ast.expr, pydantic_names: set[str]) -> bool:
    """A stdlib @dataclass or posthog @frozen decorator; names bound by pydantic imports are excluded."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    dotted = _dotted_name(target)
    if dotted is None or "pydantic" in dotted:
        return False
    if dotted.split(".")[0] in pydantic_names:
        return False
    return dotted in ("dataclass", "frozen") or dotted.endswith((".dataclass", ".frozen"))


def _is_secret_name(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith("_id") or "expires" in lowered:
        return False
    return any(token in lowered for token in SECRET_NAME_TOKENS)


def _hides_repr(value: ast.expr | None, field_names: set[str]) -> bool:
    """True when the field default is a dataclasses.field(...) call carrying repr=False."""
    if not isinstance(value, ast.Call):
        return False
    if _dotted_name(value.func) not in field_names:
        return False
    return any(
        kw.arg == "repr" and isinstance(kw.value, ast.Constant) and kw.value.value is False for kw in value.keywords
    )


def _pydantic_bound_names(tree: ast.Module) -> set[str]:
    """Local names bound by pydantic imports. Resolving decorator provenance per class (instead of
    skipping the whole module) keeps stdlib dataclasses inspected in mixed modules where
    `from pydantic.dataclasses import dataclass` would otherwise be indistinguishable by name."""
    names: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.ImportFrom(module=str(module), names=aliases) if module == "pydantic" or module.startswith(
                "pydantic."
            ):
                names.update(alias.asname or alias.name for alias in aliases)
            case ast.Import(names=aliases):
                for alias in aliases:
                    if alias.name == "pydantic" or alias.name.startswith("pydantic."):
                        names.add(alias.asname or alias.name.split(".")[0])
    return names


def _dataclass_field_names(tree: ast.Module) -> set[str]:
    """Module-level names that resolve to dataclasses.field, so a look-alike helper cannot pass as one."""
    names: set[str] = set()
    for node in tree.body:
        match node:
            case ast.ImportFrom(module="dataclasses", names=aliases):
                names.update(alias.asname or alias.name for alias in aliases if alias.name == "field")
            case ast.Import(names=aliases):
                names.update(f"{alias.asname or alias.name}.field" for alias in aliases if alias.name == "dataclasses")
    return names


def _is_test_file(path: Path) -> bool:
    return path.name == "conftest.py" or path.name.startswith("test_")


def _candidate_paths() -> list[Path]:
    """Tracked Python files with a dataclass decorator, found by git grep so most files are never read."""
    pathspecs = [f"{root}/**/*.py" for root in SCANNED_ROOTS]
    result = subprocess.run(
        ["git", "grep", "-l", "-E", "-e", "@([A-Za-z_]+\\.)?(dataclass|frozen)", "--", *pathspecs],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(REPO_ROOT / line for line in result.stdout.splitlines())


def collect_violations() -> list[str]:
    violations: list[str] = []
    for path in _candidate_paths():
        if SKIPPED_DIRS.intersection(path.parts) or _is_test_file(path):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        # Parsing dominates the run time, so skip files that cannot hold a secret-looking name.
        if not any(token in source.lower() for token in SECRET_NAME_TOKENS):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        pydantic_names = _pydantic_bound_names(tree)
        field_names = _dataclass_field_names(tree)
        relpath = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(_is_dataclass_decorator(decorator, pydantic_names) for decorator in node.decorator_list):
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                    continue
                if isinstance(stmt.annotation, ast.Name) and stmt.annotation.id == "bool":
                    continue
                if _is_secret_name(stmt.target.id) and not _hides_repr(stmt.value, field_names):
                    violations.append(f"{relpath} {node.name}.{stmt.target.id}")
    return violations


def read_exemptions() -> set[str]:
    return {line.strip() for line in EXEMPTIONS_PATH.read_text().splitlines() if line.strip()}


def test_secret_dataclass_fields_hide_repr() -> None:
    violations = sorted(set(collect_violations()) - read_exemptions())
    assert not violations, (
        "Dataclass fields with secret-looking names must be declared with field(repr=False) "
        "so repr() cannot leak them into tracebacks and logs. Fix them, or if a flagged field "
        "is genuinely not a secret, add it to posthog/test/repo_invariants/dataclass_secret_field_exemptions.txt:\n"
        + "\n".join(violations)
    )


if __name__ == "__main__":
    collected = set(collect_violations())
    exemptions = read_exemptions()
    for violation in sorted(collected - exemptions):
        print(violation)  # noqa: T201
    for stale in sorted(exemptions - collected):
        print(f"stale exemption: {stale}")  # noqa: T201
    print(f"{len(collected - exemptions)} violations, {len(exemptions)} exemptions")  # noqa: T201
