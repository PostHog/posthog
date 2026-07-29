"""Canvas source project validation and legacy `meta.code` compatibility.

A canvas source project is the multi-file write format for canvases (see the
canvas application build pipeline plan). The entry component is also stored in
the dashboard row's `meta.code` while the compatibility renderer remains; this
module maps between the two shapes:

- a legacy canvas is presented as a *synthetic* source project whose entry
  mounts the stored React component;
- a published source project is validated for the authoritative builder and its
  entry component is mirrored to `meta.code` for the compatibility renderer.

Everything here is pure — no I/O, no ORM — so it can be exercised without a
database and reused by the build workers later.
"""

import re
from typing import Any

CANVAS_SOURCE_SCHEMA_VERSION = 1
CANVAS_ENTRY_HTML = "index.html"
# The conventional React entry component mirrored into the legacy runtime.
CANVAS_COMPONENT_PATH = "src/canvas.tsx"
# Version of the host-injected `ph` postMessage bridge the legacy runtime speaks.
CANVAS_SDK_VERSION = "0.1.0"

MAX_SOURCE_FILES = 64
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024

# Platform-supported dependencies, pinned to the exact versions the legacy
# runtime's import map resolves (mirrors FREEFORM_WHITELIST in posthog/code).
PLATFORM_DEPENDENCIES: dict[str, str] = {
    "react": "19.0.0",
    "react-dom": "19.0.0",
    "@posthog/quill": "0.3.0-beta.18",
    "recharts": "2.15.0",
    "lucide-react": "1.21.0",
    "dayjs": "1.11.13",
}

# Import specifiers the legacy runtime resolves. Exact-match only, so a subpath
# can't smuggle in an unreviewed entry point.
ALLOWED_IMPORT_SPECIFIERS = frozenset(
    [
        "react",
        "react-dom",
        "react-dom/client",
        "@posthog/quill",
        "recharts",
        "lucide-react",
        "dayjs",
    ]
)

# The synthetic entry shell. The legacy runtime compiles and mounts the default
# export of the component file itself, so this file is informational: it makes
# the project a self-describing web project and reserves the layout the build
# service will compile for real.
SYNTHETIC_INDEX_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <div id="root"></div>
    <!-- Legacy canvas: the host runtime mounts the default export of src/canvas.tsx. -->
    <script type="module" src="/src/canvas.tsx"></script>
  </body>
</html>
"""

# Matches static module specifiers: `from "spec"` (import-with-bindings and
# export-from) or a bare side-effect `import "spec"`. Regex-based like the
# client-side check, so a literal `from "x"` inside a string can still fool it —
# acceptable for the legacy tier; the build service parses for real.
_STATIC_IMPORT_RE = re.compile(r"\bfrom\s*[\"']([^\"']+)[\"']|\bimport\s*[\"']([^\"']+)[\"']")

# Out-of-band code loading the legacy sandbox rejects outright.
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


def synthetic_source_project(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Present a legacy `meta.code` canvas as a source project.

    The component file carries the stored source verbatim (empty string for a
    canvas that has never been published), and the entry HTML is the fixed
    synthetic shell.
    """
    code = (meta or {}).get("code")
    return {
        "schemaVersion": CANVAS_SOURCE_SCHEMA_VERSION,
        "files": {
            CANVAS_ENTRY_HTML: SYNTHETIC_INDEX_HTML,
            CANVAS_COMPONENT_PATH: code if isinstance(code, str) else "",
        },
        "entryHtml": CANVAS_ENTRY_HTML,
        "dependencies": dict(PLATFORM_DEPENDENCIES),
        "canvasSdkVersion": CANVAS_SDK_VERSION,
    }


def extract_legacy_code(project: dict[str, Any]) -> str:
    """The single-file React source a valid legacy-compatible project reduces to."""
    return project["files"].get(CANVAS_COMPONENT_PATH, "")


def _validate_path(path: str) -> str | None:
    if path == "" or path.startswith("/") or "\\" in path:
        return "file paths must be relative, non-empty, and use forward slashes"
    segments = path.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            return "file paths must not contain empty, '.', or '..' segments"
        if not _PATH_SEGMENT_RE.match(segment):
            return "file path segments may only contain letters, digits, '.', '_', '@', and '-'"
    return None


def _line_of(code: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.search(code)
    if match is None:
        return None
    return code.count("\n", 0, match.start()) + 1


def _validate_component_source(code: str) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []

    for pattern, code_name, message in _FORBIDDEN_PATTERNS:
        line = _line_of(code, pattern)
        if line is not None:
            diagnostics.append(diagnostic("error", code_name, message, path=CANVAS_COMPONENT_PATH, line=line))

    for pattern, code_name, message in _NETWORK_PATTERNS:
        line = _line_of(code, pattern)
        if line is not None:
            diagnostics.append(diagnostic("warning", code_name, message, path=CANVAS_COMPONENT_PATH, line=line))

    for match in _STATIC_IMPORT_RE.finditer(code):
        specifier = match.group(1) or match.group(2)
        if specifier and not specifier.startswith(("./", "../", "/")) and specifier not in ALLOWED_IMPORT_SPECIFIERS:
            line = code.count("\n", 0, match.start()) + 1
            diagnostics.append(
                diagnostic(
                    "error",
                    "import_not_allowed",
                    f'import of module "{specifier}" is not supported — allowed imports: '
                    + ", ".join(sorted(ALLOWED_IMPORT_SPECIFIERS)),
                    path=CANVAS_COMPONENT_PATH,
                    line=line,
                )
            )

    return diagnostics


def validate_source_project(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a candidate source project against the build contract.

    Returns structured diagnostics; an empty list (or warnings only) means the
    project is publishable. Mirrors the build pipeline's stage-1 validation
    (schema, paths, file count, total size) plus dependency and runtime safety
    constraints. The authoritative builder performs module-graph validation.
    """
    diagnostics: list[dict[str, Any]] = []

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
    if len(files) > MAX_SOURCE_FILES:
        diagnostics.append(
            diagnostic("error", "too_many_files", f"a source project may contain at most {MAX_SOURCE_FILES} files")
        )

    total_bytes = 0
    for path, content in files.items():
        path_problem = _validate_path(path)
        if path_problem is not None:
            diagnostics.append(diagnostic("error", "invalid_path", path_problem, path=path))
            continue
        size = len(content.encode("utf-8"))
        total_bytes += size
        if size > MAX_FILE_BYTES:
            diagnostics.append(
                diagnostic(
                    "error",
                    "file_too_large",
                    f"file exceeds the {MAX_FILE_BYTES // 1024} KB per-file limit",
                    path=path,
                )
            )
    for path, asset in (project.get("assets") or {}).items():
        path_problem = _validate_path(path)
        if path_problem is not None:
            diagnostics.append(diagnostic("error", "invalid_path", path_problem, path=path))
            continue
        size = (len(asset.get("content", "")) * 3) // 4
        total_bytes += size
        if size > MAX_TOTAL_BYTES:
            diagnostics.append(
                diagnostic(
                    "error",
                    "file_too_large",
                    f"asset exceeds the {MAX_TOTAL_BYTES // 1024} KB per-file limit",
                    path=path,
                )
            )
    if total_bytes > MAX_TOTAL_BYTES:
        diagnostics.append(
            diagnostic(
                "error",
                "project_too_large",
                f"the source project exceeds the {MAX_TOTAL_BYTES // 1024} KB total size limit",
            )
        )

    dependencies = project.get("dependencies") or {}
    for name, version in dependencies.items():
        pinned = PLATFORM_DEPENDENCIES.get(name)
        if pinned is None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "dependency_not_admitted",
                    f'dependency "{name}" is not platform-supported — supported: '
                    + ", ".join(sorted(PLATFORM_DEPENDENCIES)),
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

    component = files.get(CANVAS_COMPONENT_PATH)
    if isinstance(component, str):
        diagnostics.extend(_validate_component_source(component))

    return diagnostics
