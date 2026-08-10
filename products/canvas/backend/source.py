"""Canvas source-project validation.

A canvas source project is the multi-file write format for canvases. This
module validates candidate projects against the platform contract (pinned
dependencies, size limits, runtime safety, declared capabilities) and presents
pre-relational single-file canvases as a synthetic project until their next
real publish.

Everything here is pure — no I/O beyond the contract manifest, no ORM — so it
can be exercised without a database and shared with the build worker.
"""

import re
import json
from typing import Any

from products.canvas.backend.contract import (
    allowed_import_specifiers,
    canvas_sdk_version,
    contract_limits,
    platform_dependencies,
)

CANVAS_SOURCE_SCHEMA_VERSION = 1
CANVAS_ENTRY_HTML = "index.html"
# The conventional React entry component (also what the synthetic shell mounts).
CANVAS_COMPONENT_PATH = "src/canvas.tsx"

# File extensions whose content is scanned as source code.
_CODE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")

# The synthetic entry shell presented for pre-relational canvases whose only
# source is a single stored React component.
SYNTHETIC_INDEX_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/canvas.tsx"></script>
  </body>
</html>
"""

# Matches static module specifiers: `from "spec"` (import-with-bindings and
# export-from) or a bare side-effect `import "spec"`. Regex-based, so a literal
# `from "x"` inside a string can still fool it — the builder parses for real.
_STATIC_IMPORT_RE = re.compile(r"\bfrom\s*[\"']([^\"']+)[\"']|\bimport\s*[\"']([^\"']+)[\"']")

# Out-of-band code loading the sandbox rejects outright.
_FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bimport\s*\("), "forbidden_dynamic_import", "dynamic import() is not allowed"),
    (re.compile(r"\brequire\s*\("), "forbidden_require", "require() is not allowed"),
    (re.compile(r"\bimportScripts\s*\("), "forbidden_import_scripts", "importScripts() is not allowed"),
    (re.compile(r"<script\b", re.IGNORECASE), "forbidden_inline_script", "inline <script> is not allowed"),
]

# Direct network calls: the `ph` bridge is the only sanctioned data path. The
# sandbox CSP blocks these at runtime, so surface them as warnings (the regex
# can't tell code from a comment or string).
_NETWORK_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"\bfetch\s*\("),
        "network_fetch",
        "fetch() is blocked by the canvas sandbox — use the `ph` data bridge instead",
    ),
    (
        re.compile(r"\bXMLHttpRequest\b"),
        "network_xhr",
        "XMLHttpRequest is blocked by the canvas sandbox — use the `ph` data bridge instead",
    ),
]

# `ph` bridge calls checked against the project's declared capabilities. The
# host enforces capabilities at runtime, so an undeclared call would build fine
# and then die in view mode — validating here turns that into a diagnostic the
# publishing agent can self-correct on.
_PH_LOAD_INSIGHT_RE = re.compile(r"\bph\s*\.\s*loadInsight\s*\(\s*(?:[\"']([^\"']+)[\"'])?")
_PH_QUERY_RE = re.compile(r"\bph\s*\.\s*query\s*\(")
_PH_CAPTURE_RE = re.compile(r"\bph\s*\.\s*capture\s*\(\s*(?:[\"']([^\"']+)[\"'])?")

_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._@-]+$")


def diagnostic(
    severity: str, code: str, message: str, path: str | None = None, line: int | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if path is not None:
        entry["path"] = path
    if line is not None:
        entry["line"] = line
    return entry


def has_errors(diagnostics: list[dict[str, Any]]) -> bool:
    return any(entry["severity"] == "error" for entry in diagnostics)


def synthetic_source_project(legacy_code: str | None) -> dict[str, Any]:
    """Present a pre-relational single-file canvas as a source project.

    The component file carries the stored source verbatim (empty string for a
    canvas that has never been published), and the entry HTML is the fixed
    synthetic shell.
    """
    return {
        "schemaVersion": CANVAS_SOURCE_SCHEMA_VERSION,
        "files": {
            CANVAS_ENTRY_HTML: SYNTHETIC_INDEX_HTML,
            CANVAS_COMPONENT_PATH: legacy_code if isinstance(legacy_code, str) else "",
        },
        "entryHtml": CANVAS_ENTRY_HTML,
        "dependencies": platform_dependencies(),
        "canvasSdkVersion": canvas_sdk_version(),
    }


def apply_source_edits(
    project: dict[str, Any], operations: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply per-file set/delete operations to a source project.

    Returns the edited project (input untouched) and diagnostics; any
    diagnostic means the edit set could not be applied atomically.
    """
    project = {**project, "files": dict(project["files"])}
    diagnostics: list[dict[str, Any]] = []
    for operation in operations:
        path = operation["path"]
        content = operation.get("content")
        if content is None:
            if path not in project["files"]:
                diagnostics.append(
                    diagnostic(
                        "error",
                        "edit_target_missing",
                        f"cannot delete {path} — the project has no file at that path",
                        path=path,
                    )
                )
                continue
            del project["files"][path]
        else:
            project["files"][path] = content
    return project, diagnostics


def validate_relative_path(path: str, *, restrict_charset: bool = True) -> str | None:
    """Validate a relative, forward-slash file path; returns the problem or None.

    Source-project paths keep the strict segment charset; artifact paths
    (``restrict_charset=False``) only reject control characters.
    """
    if path == "" or path.startswith("/") or "\\" in path:
        return "file paths must be relative, non-empty, and use forward slashes"
    if any(character in path for character in "\r\n\0"):
        return "file paths must not contain control characters"
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            return "file paths must not contain empty, '.', or '..' segments"
        if restrict_charset and not _PATH_SEGMENT_RE.match(segment):
            return "file path segments may only contain letters, digits, '.', '_', '@', and '-'"
    return None


def _line_of(code: str, position: int) -> int:
    return code.count("\n", 0, position) + 1


def _validate_code_file(path: str, code: str) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []

    for pattern, code_name, message in _FORBIDDEN_PATTERNS:
        for match in pattern.finditer(code):
            diagnostics.append(diagnostic("error", code_name, message, path=path, line=_line_of(code, match.start())))

    for pattern, code_name, message in _NETWORK_PATTERNS:
        for match in pattern.finditer(code):
            diagnostics.append(diagnostic("warning", code_name, message, path=path, line=_line_of(code, match.start())))

    allowed = allowed_import_specifiers()
    for match in _STATIC_IMPORT_RE.finditer(code):
        specifier = match.group(1) or match.group(2)
        if not specifier or specifier.startswith(("./", "../", "/")):
            continue
        # Local worker imports carry a ?worker suffix; strip it before checking.
        if specifier not in allowed and specifier.removesuffix("?worker") not in allowed:
            diagnostics.append(
                diagnostic(
                    "error",
                    "import_not_allowed",
                    f'import of module "{specifier}" is not supported — allowed imports: ' + ", ".join(sorted(allowed)),
                    path=path,
                    line=_line_of(code, match.start()),
                )
            )

    return diagnostics


def _validate_capabilities(path: str, code: str, capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    """Check `ph` bridge calls against the project's declared capabilities."""
    diagnostics: list[dict[str, Any]] = []
    posthog_capabilities = capabilities.get("posthog") or {}
    declared_insights = set(posthog_capabilities.get("insights") or [])
    declared_events = set(posthog_capabilities.get("captureEvents") or [])
    inline_queries = bool(posthog_capabilities.get("inlineQueries"))

    for match in _PH_LOAD_INSIGHT_RE.finditer(code):
        short_id = match.group(1)
        line = _line_of(code, match.start())
        if short_id is not None and short_id not in declared_insights:
            diagnostics.append(
                diagnostic(
                    "error",
                    "capability_missing_insight",
                    f'ph.loadInsight("{short_id}") requires "{short_id}" in capabilities.posthog.insights — '
                    "the host rejects undeclared insights at runtime",
                    path=path,
                    line=line,
                )
            )
        elif short_id is None and not declared_insights:
            diagnostics.append(
                diagnostic(
                    "warning",
                    "capability_missing_insight",
                    "ph.loadInsight() is called with a dynamic id but capabilities.posthog.insights is empty — "
                    "declare every insight short id the canvas loads",
                    path=path,
                    line=line,
                )
            )

    if not inline_queries:
        query_match = _PH_QUERY_RE.search(code)
        if query_match is not None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "capability_missing_inline_queries",
                    "ph.query() requires capabilities.posthog.inlineQueries: true — "
                    "the host rejects undeclared inline queries at runtime",
                    path=path,
                    line=_line_of(code, query_match.start()),
                )
            )

    for match in _PH_CAPTURE_RE.finditer(code):
        event = match.group(1)
        line = _line_of(code, match.start())
        if event is not None and event not in declared_events:
            diagnostics.append(
                diagnostic(
                    "error",
                    "capability_missing_capture_event",
                    f'ph.capture("{event}") requires "{event}" in capabilities.posthog.captureEvents — '
                    "the host rejects undeclared events at runtime",
                    path=path,
                    line=line,
                )
            )
        elif event is None and not declared_events:
            diagnostics.append(
                diagnostic(
                    "warning",
                    "capability_missing_capture_event",
                    "ph.capture() is called with a dynamic event but capabilities.posthog.captureEvents is empty — "
                    "declare every event name the canvas captures",
                    path=path,
                    line=line,
                )
            )

    return diagnostics


def validate_source_project(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a candidate source project against the platform contract.

    Returns structured diagnostics; an empty list (or warnings only) means the
    project is publishable. Mirrors the build pipeline's stage-1 validation
    (schema, paths, file count, total size) plus dependency, runtime-safety,
    and capability constraints. The authoritative builder performs
    module-graph validation.
    """
    diagnostics: list[dict[str, Any]] = []
    limits = contract_limits()

    if project.get("schemaVersion") != CANVAS_SOURCE_SCHEMA_VERSION:
        diagnostics.append(
            diagnostic(
                "error",
                "unsupported_schema_version",
                f"schemaVersion must be {CANVAS_SOURCE_SCHEMA_VERSION}",
            )
        )

    if project.get("entryHtml") != CANVAS_ENTRY_HTML:
        diagnostics.append(diagnostic("error", "invalid_entry", f'entryHtml must be "{CANVAS_ENTRY_HTML}"'))

    files = project.get("files") or {}
    assets = project.get("assets") or {}
    if project.get("entryHtml") not in files:
        diagnostics.append(diagnostic("error", "missing_entry", "entryHtml must name a file present in files"))
    network_origins = ((project.get("capabilities") or {}).get("network") or {}).get("origins") or []
    if network_origins:
        diagnostics.append(
            diagnostic("error", "network_origins_not_supported", "capabilities.network.origins must be empty")
        )
    if len(files) + len(assets) > limits["maxSourceFiles"]:
        diagnostics.append(
            diagnostic(
                "error",
                "too_many_files",
                f"a source project may contain at most {limits['maxSourceFiles']} files",
            )
        )

    total_bytes = 0
    for path, content in files.items():
        path_problem = validate_relative_path(path)
        if path_problem is not None:
            diagnostics.append(diagnostic("error", "invalid_path", path_problem, path=path))
            continue
        size = len(content.encode("utf-8"))
        total_bytes += size
        if size > limits["maxSourceFileBytes"]:
            diagnostics.append(
                diagnostic(
                    "error",
                    "file_too_large",
                    f"file exceeds the {limits['maxSourceFileBytes'] // 1024} KB per-file limit",
                    path=path,
                )
            )
    for path, asset in assets.items():
        path_problem = validate_relative_path(path)
        if path_problem is not None:
            diagnostics.append(diagnostic("error", "invalid_path", path_problem, path=path))
            continue
        size = (len(asset.get("content", "")) * 3) // 4
        total_bytes += size
        if size > limits["maxSourceTotalBytes"]:
            diagnostics.append(
                diagnostic(
                    "error",
                    "file_too_large",
                    f"asset exceeds the {limits['maxSourceTotalBytes'] // 1024} KB per-file limit",
                    path=path,
                )
            )
    canonical_size = len(json.dumps(project, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    if total_bytes > limits["maxSourceTotalBytes"] or canonical_size > limits["maxSourceTotalBytes"]:
        diagnostics.append(
            diagnostic(
                "error",
                "project_too_large",
                f"the source project exceeds the {limits['maxSourceTotalBytes'] // 1024} KB total size limit",
            )
        )

    pinned_dependencies = platform_dependencies()
    for name, version in (project.get("dependencies") or {}).items():
        pinned = pinned_dependencies.get(name)
        if pinned is None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "dependency_not_admitted",
                    f'dependency "{name}" is not platform-supported — supported: '
                    + ", ".join(sorted(pinned_dependencies)),
                )
            )
        elif version != pinned:
            diagnostics.append(
                diagnostic(
                    "error",
                    "dependency_version_mismatch",
                    f'dependency "{name}" must be the platform-pinned version {pinned}, got {version}',
                )
            )

    capabilities = project.get("capabilities") or {}
    for path, content in files.items():
        if not path.endswith(_CODE_EXTENSIONS) or not isinstance(content, str):
            continue
        diagnostics.extend(_validate_code_file(path, content))
        diagnostics.extend(_validate_capabilities(path, content, capabilities))

    return diagnostics
