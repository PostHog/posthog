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

import jsonschema

from products.canvas.backend.actions import CANVAS_ACTIONS
from products.canvas.backend.contract import (
    MAX_COMPONENT_HEIGHT,
    MAX_COMPONENT_WIDTH,
    allowed_import_specifiers,
    canonical_network_origin,
    canvas_sdk_version,
    contract_limits,
    platform_dependencies,
)

CANVAS_SOURCE_SCHEMA_VERSION = 1
CANVAS_ENTRY_HTML = "index.html"
# The conventional React entry component (also what the synthetic shell mounts).
CANVAS_COMPONENT_PATH = "src/canvas.tsx"

# Config schemas are author-supplied, so the vocabulary is an allowlist:
# no $ref/$dynamicRef (nothing downstream may be induced to resolve one) and
# no pattern/patternProperties (placement-config validation must not evaluate
# author-supplied regexes). Size-capped so a schema cannot bloat version rows.
MAX_CONFIG_SCHEMA_BYTES = 16 * 1024
# Depth-capped as well: a schema well under the byte cap can still nest deeply
# enough to exhaust the Python recursion limit inside jsonschema's check_schema
# (or our own keyword scan), which would escape as a 500 rather than a validation
# diagnostic. Bounded far below where check_schema starts recursing off the limit.
MAX_CONFIG_SCHEMA_DEPTH = 32
ALLOWED_CONFIG_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "title",
        "description",
        "default",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "format",
    }
)

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
_PH_STATE_RE = re.compile(r"\bph\s*\.\s*state\s*\.")
_PH_STATE_CALL_RE = re.compile(r"\bph\s*\.\s*state\s*\.\s*(get|set|list)\s*\(")
_STATE_SCOPE_LITERAL_RE = re.compile(r"\bscope\s*:\s*[\"']([^\"']+)[\"']")
_PH_ACTIONS_RE = re.compile(r"\bph\s*\.\s*actions\s*\.\s*invoke\s*\(\s*(?:[\"']([^\"']+)[\"'])?")
_PH_AGENT_REQUEST_RE = re.compile(r"\bph\s*\.\s*agent\s*\.\s*request\s*\(")

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


def _validate_network_origin(origin: Any) -> str | None:
    if not isinstance(origin, str):
        return "network origins must be strings"
    canonical = canonical_network_origin(origin)
    if canonical is None:
        return (
            "network origins must be exact HTTPS origins without paths, credentials, queries, fragments, or wildcards"
        )
    if origin.rstrip("/") != canonical:
        return f'network origin must use its canonical form: "{canonical}"'
    return None


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
    agent_requests = bool(posthog_capabilities.get("agentRequests"))

    declared_state = set(posthog_capabilities.get("state") or [])
    if not declared_state:
        state_match = _PH_STATE_RE.search(code)
        if state_match is not None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "capability_missing_state",
                    'ph.state requires its scopes in capabilities.posthog.state (["user"] and/or ["shared"]) — '
                    "the host rejects undeclared state access at runtime",
                    path=path,
                    line=_line_of(code, state_match.start()),
                )
            )
    else:
        # Declaring one scope is not declaring the other: check each call
        # site's scope — the explicit literal, or the runtime's "user"
        # default when get/set pass no options — against the declaration.
        for call in _PH_STATE_CALL_RE.finditer(code):
            window_end = min(len(code), call.end() + 200)
            next_call = _PH_STATE_CALL_RE.search(code, call.end())
            if next_call is not None:
                window_end = min(window_end, next_call.start())
            scope_literal = _STATE_SCOPE_LITERAL_RE.search(code, call.end(), window_end)
            used_scope = scope_literal.group(1) if scope_literal else None
            if used_scope is None:
                used_scope = "user" if call.group(1) in ("get", "set") else None
            if used_scope is not None and used_scope not in declared_state:
                line = _line_of(code, call.start())
                detail = (
                    f'ph.state.{call.group(1)} uses scope "{used_scope}"'
                    if scope_literal
                    else f'ph.state.{call.group(1)} defaults to scope "user"'
                )
                diagnostics.append(
                    diagnostic(
                        "error",
                        "capability_missing_state",
                        f"{detail}, which capabilities.posthog.state does not declare — "
                        "the host rejects undeclared state access at runtime",
                        path=path,
                        line=line,
                    )
                )

    declared_action_verbs = set(posthog_capabilities.get("actions") or [])
    for match in _PH_ACTIONS_RE.finditer(code):
        verb = match.group(1)
        line = _line_of(code, match.start())
        if verb is not None and verb not in declared_action_verbs:
            diagnostics.append(
                diagnostic(
                    "error",
                    "capability_missing_action",
                    f'ph.actions.invoke("{verb}") requires "{verb}" in capabilities.posthog.actions — '
                    "the host rejects undeclared actions at runtime",
                    path=path,
                    line=line,
                )
            )
        elif verb is None and not declared_action_verbs:
            diagnostics.append(
                diagnostic(
                    "warning",
                    "capability_missing_action",
                    "ph.actions.invoke() is called with a dynamic verb but capabilities.posthog.actions is empty — "
                    "declare every verb the canvas invokes",
                    path=path,
                    line=line,
                )
            )

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

    if not agent_requests:
        request_match = _PH_AGENT_REQUEST_RE.search(code)
        if request_match is not None:
            diagnostics.append(
                diagnostic(
                    "error",
                    "capability_missing_agent_requests",
                    "ph.agent.request() requires capabilities.posthog.agentRequests: true — "
                    "the host rejects undeclared agent requests at runtime",
                    path=path,
                    line=_line_of(code, request_match.start()),
                )
            )

    return diagnostics


def _validate_component_size(size: Any) -> str | None:
    """Validate a component's grid-size contract; returns the problem or None."""
    if not isinstance(size, dict):
        return "component.size must be an object with defaultW, defaultH, minW, and minH"
    for key in ("defaultW", "defaultH", "minW", "minH", "maxW", "maxH"):
        value = size.get(key)
        if value is None:
            if key in ("maxW", "maxH"):
                continue
            return f"component.size.{key} is required"
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            return f"component.size.{key} must be a positive integer"
    for axis, cap in (("W", MAX_COMPONENT_WIDTH), ("H", MAX_COMPONENT_HEIGHT)):
        maximum = size.get(f"max{axis}", cap)
        if maximum > cap:
            return f"component.size.max{axis} may not exceed {cap}"
        if not size[f"min{axis}"] <= size[f"default{axis}"] <= maximum:
            return f"component.size must satisfy min{axis} <= default{axis} <= max{axis} (cap {cap})"
    return None


def _unknown_config_schema_keywords(schema: Any) -> set[str]:
    """Every schema keyword used anywhere in the schema tree that is not allowlisted."""
    if not isinstance(schema, dict):
        return set()
    unknown = {key for key in schema if key not in ALLOWED_CONFIG_SCHEMA_KEYWORDS}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            for nested in value.values():
                unknown |= _unknown_config_schema_keywords(nested)
        elif key in ("items", "additionalProperties"):
            unknown |= _unknown_config_schema_keywords(value)
    return unknown


def _max_json_depth(value: Any) -> int:
    """Deepest container nesting in a JSON value, walked with an explicit stack.

    Author config schemas are hostile input, so depth is measured without
    recursion — the point is to bound nesting before any recursive processing
    (the keyword scan, jsonschema's check_schema) descends into it.
    """
    max_depth = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, dict):
            children: Any = current.values()
        elif isinstance(current, list):
            children = current
        else:
            continue
        if depth > max_depth:
            max_depth = depth
        for child in children:
            stack.append((child, depth + 1))
    return max_depth


def _validate_config_schema(config_schema: Any) -> str | None:
    """Validate a component's placement-config schema; returns the problem or None."""
    if not isinstance(config_schema, dict) or config_schema.get("type") != "object":
        return 'component.configSchema must be a JSON Schema object with "type": "object"'
    if len(json.dumps(config_schema, separators=(",", ":")).encode("utf-8")) > MAX_CONFIG_SCHEMA_BYTES:
        return f"component.configSchema may not exceed {MAX_CONFIG_SCHEMA_BYTES // 1024} KB serialized"
    if _max_json_depth(config_schema) > MAX_CONFIG_SCHEMA_DEPTH:
        return f"component.configSchema may not nest deeper than {MAX_CONFIG_SCHEMA_DEPTH} levels"
    unknown = _unknown_config_schema_keywords(config_schema)
    if unknown:
        return (
            "component.configSchema uses unsupported keywords: "
            + ", ".join(sorted(unknown))
            + " — supported: "
            + ", ".join(sorted(ALLOWED_CONFIG_SCHEMA_KEYWORDS))
        )
    try:
        jsonschema.Draft202012Validator.check_schema(config_schema)
    except jsonschema.SchemaError as error:
        return f"component.configSchema is not a valid JSON Schema: {error.message}"
    return None


def validate_component_meta(project: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Validate a project's component placement contract for its canvas kind.

    Components must declare how grids may place them (size, optional config
    schema); every other kind must not carry a contract, so an author cannot
    believe a freeform canvas is placeable.
    """
    meta = project.get("component")
    if kind != "component":
        if meta:
            return [
                diagnostic(
                    "error",
                    "component_meta_not_allowed",
                    "only component-kind canvases may declare a `component` placement contract",
                )
            ]
        return []
    if not isinstance(meta, dict):
        return [
            diagnostic(
                "error",
                "component_meta_missing",
                "a component project must declare `component` with a `size` contract "
                '(e.g. {"size": {"defaultW": 2, "defaultH": 1, "minW": 1, "minH": 1}})',
            )
        ]
    diagnostics: list[dict[str, Any]] = []
    size_problem = _validate_component_size(meta.get("size"))
    if size_problem is not None:
        diagnostics.append(diagnostic("error", "component_size_invalid", size_problem))
    if meta.get("configSchema") is not None:
        schema_problem = _validate_config_schema(meta["configSchema"])
        if schema_problem is not None:
            diagnostics.append(diagnostic("error", "component_config_schema_invalid", schema_problem))
    return diagnostics


def validate_source_project(project: dict[str, Any], *, kind: str = "freeform") -> list[dict[str, Any]]:
    """Validate a candidate source project against the platform contract.

    Returns structured diagnostics; an empty list (or warnings only) means the
    project is publishable. Mirrors the build pipeline's stage-1 validation
    (schema, paths, file count, total size) plus dependency, runtime-safety,
    and capability constraints. The authoritative builder performs
    module-graph validation. ``kind`` is the owning canvas's kind — it gates
    the component placement contract, which only component projects carry.
    """
    diagnostics: list[dict[str, Any]] = list(validate_component_meta(project, kind))
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
    for origin in network_origins:
        problem = _validate_network_origin(origin)
        if problem is not None:
            diagnostics.append(diagnostic("error", "invalid_network_origin", problem))
    declared_verbs = ((project.get("capabilities") or {}).get("posthog") or {}).get("actions") or []
    unregistered = sorted(set(declared_verbs) - set(CANVAS_ACTIONS))
    if unregistered:
        diagnostics.append(
            diagnostic(
                "error",
                "action_not_registered",
                "capabilities.posthog.actions declares unknown verbs: "
                + ", ".join(unregistered)
                + " — registered verbs: "
                + ", ".join(sorted(CANVAS_ACTIONS)),
            )
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
