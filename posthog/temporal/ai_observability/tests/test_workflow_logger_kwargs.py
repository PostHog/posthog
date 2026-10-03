import ast
import pathlib

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]

STDLIB_LOG_KWARGS = frozenset({"exc_info", "stack_info", "stacklevel", "extra"})
LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})


def _targets_workflow_logger(node: ast.expr) -> bool:
    if not isinstance(node, ast.Attribute) or node.attr != "logger":
        return False
    owner = node.value
    if isinstance(owner, ast.Name):
        return owner.id == "workflow"
    return isinstance(owner, ast.Attribute) and owner.attr == "workflow"


def _find_offenders() -> list[str]:
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in LOG_METHODS or not _targets_workflow_logger(node.func.value):
                continue
            extras = sorted(k.arg for k in node.keywords if k.arg and k.arg not in STDLIB_LOG_KWARGS)
            if extras:
                rel = path.relative_to(PACKAGE_ROOT)
                offenders.append(f"{rel}:{node.lineno} .{node.func.attr}({', '.join(f'{k}=' for k in extras)})")
    return offenders


def test_workflow_logger_is_never_called_with_structlog_kwargs() -> None:
    offenders = _find_offenders()
    assert not offenders, (
        "temporalio's workflow.logger is a stdlib LoggerAdapter, so it raises TypeError on "
        "structlog-style keyword arguments. The raise happens in workflow code, which fails the "
        "workflow task and retries it forever, so the workflow hangs until its execution timeout "
        "instead of failing fast.\n\n"
        "Use this package's module-level structlog logger instead, which keeps the fields "
        "queryable:\n"
        "    logger = structlog.get_logger(__name__)\n"
        "    logger.info('message', team_id=team_id)\n\n"
        "Offending calls:\n" + "\n".join(f"  {line}" for line in offenders)
    )
