"""Parse and serialize .sql model files with SQL comment annotations.

Annotations are SQL comments starting with `-- @`. For example:

    -- @description Monthly active users by plan type
    -- @materialize
    -- @tags marketing, finance

Shorthand conventions:
    @desc -> @description
    @mat  -> @materialize
    @view -> @view (ephemeral; default)

A bare .sql file with no annotations is a valid non-materialized view.

Sync frequency is configured at the DAG level in posthog.toml, not per model.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class ParsedModelFile:
    """Parsed representation of a .sql model file."""

    query: str
    description: str = ""
    materialized: bool = False
    tags: list[str] = field(default_factory=list)

    def set_materialized(self):
        self.materialized = True

    def set_view(self):
        self.materialized = False

    def set_description(self, description: str):
        self.description = description

    def set_tags(self, tags: str):
        self.tags = [t.strip() for t in tags.split(",") if t.strip()]


# Matches lines like: -- @directive value
_ANNOTATION_RE = re.compile(r"^--\s*@(\w+)\s*(.*?)\s*$")

# Shorthand aliases
_DIRECTIVE_ALIASES: dict[str, str] = {
    "desc": "description",
    "mat": "materialize",
}

# require no args
_NULLARY_DIRECTIVES: dict[str, Callable[[ParsedModelFile], None]] = {
    "materialize": lambda x: x.set_materialized(),
    "view": lambda x: x.set_view(),
}

# require exactly one value
_UNARY_DIRECTIVES: dict[str, Callable[[ParsedModelFile, str], None]] = {
    "description": lambda x, y: x.set_description(y),
    "tags": lambda x, y: x.set_tags(y),
}

_ALL_DIRECTIVES = set(_NULLARY_DIRECTIVES) | set(_UNARY_DIRECTIVES)

# sets of directives that cannot coexist in the same model
_MUTUALLY_EXCLUSIVE: list[set[str]] = [
    {"materialize", "view"},
]


def _parse_unary_value(directive: str, value: str, line_num: int) -> str:
    """Parse the value for a unary directive. Returns the raw string value."""
    parsed = _unquote(value)
    if not parsed:
        raise ValueError(f"Line {line_num}: @{directive} requires a value")
    return parsed


def parse_model_file(content: str) -> ParsedModelFile:
    """Parse a .sql file with optional comment annotations into a ParsedModelFile.

    Raises ValueError on:
    - Unknown annotations
    - Mutually exclusive annotations (e.g. @materialize + @view)
    - Duplicate annotations (e.g. two @description lines)
    - Missing required values (e.g. @description without text)
    - Unexpected values on nullary directives (e.g. @materialize foo)
    - Empty query body
    """
    query_lines: list[str] = []
    has_query_body = False
    seen_directives: dict[str, int] = {}  # directive -> line number
    model = ParsedModelFile(query="")

    for line_num, line in enumerate(content.splitlines(), start=1):
        match = _ANNOTATION_RE.match(line)
        if match:
            raw_directive = match.group(1).lower()
            value = match.group(2)
            directive = _DIRECTIVE_ALIASES.get(raw_directive, raw_directive)
            if directive not in _ALL_DIRECTIVES:
                raise ValueError(f"Line {line_num}: unknown annotation @{raw_directive}")
            if directive in seen_directives:
                raise ValueError(
                    f"Line {line_num}: duplicate @{directive} (first seen on line {seen_directives[directive]})"
                )
            seen_directives[directive] = line_num
            if directive in _NULLARY_DIRECTIVES:
                if value:
                    raise ValueError(f"Line {line_num}: @{directive} takes no value, got {value!r}")
                # purposefully not guarded by try. i want this to fail if we KeyError
                _NULLARY_DIRECTIVES[directive](model)
            else:
                _UNARY_DIRECTIVES[directive](model, _parse_unary_value(directive, value, line_num))
        else:
            if line.strip():
                has_query_body = True
        # keep all lines (including annotations) in the query
        query_lines.append(line)
    # validate mutually exclusive directives
    for exclusive_set in _MUTUALLY_EXCLUSIVE:
        found = exclusive_set & seen_directives.keys()
        if len(found) > 1:
            sorted_found = sorted(found)
            raise ValueError(
                f"Conflicting annotations: @{sorted_found[0]} and @{sorted_found[1]} "
                f"cannot both be present in the same model"
            )
    query = "\n".join(query_lines).strip()
    if not has_query_body:
        raise ValueError("Model file contains no SQL query")
    model.query = query
    return model


def serialize_model_file(
    query: str,
    *,
    description: str = "",
    materialized: bool = False,
    tags: list[str] | None = None,
) -> str:
    """Serialize a model to a .sql file string with comment annotations.

    Annotations are prepended as SQL comments before the query.
    If no metadata is set, returns just the SQL query.
    """
    annotation_lines: list[str] = []
    if description:
        annotation_lines.append(f"-- @description {description}")
    if materialized:
        annotation_lines.append("-- @materialize")
    if tags:
        annotation_lines.append(f"-- @tags {', '.join(tags)}")
    if not annotation_lines:
        return query.strip() + "\n"
    annotations = "\n".join(annotation_lines)
    return f"{annotations}\n{query.strip()}\n"


def model_name_from_path(file_path: str) -> str:
    """Extract the model name from a file path.

    The model name is the filename without the .sql extension.
    Subdirectories are ignored (flat namespace).

    Examples:
        "models/monthly_active_users.sql" -> "monthly_active_users"
        "models/staging/stg_events.sql" -> "stg_events"
        "environments/production/models/revenue.sql" -> "revenue"
    """
    filename = file_path.rsplit("/", 1)[-1]
    if filename.endswith(".sql"):
        filename = filename[:-4]
    return filename


def _unquote(value: str) -> str:
    """Remove surrounding single or double quotes from a string value if present."""
    value = value.strip()
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        value = value[1:-1]
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    value = value.strip()
    return value
