"""Server-side rendering for templated skills.

A skill is a *template* when its `metadata.variables` declares one or more variables. The body and
bundled files carry `{{ variable }}` placeholders that get bound to user-supplied values when the
skill is instantiated (installed) into a team. Rendering is deliberately plain string substitution —
never a template engine — so a community-published template can't execute logic against tenant data.
"""

import re
from dataclasses import dataclass
from typing import Any

# `{{ name }}` with optional surrounding whitespace. Names are Python-identifier-like.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class TemplateVariable:
    name: str
    prompt: str
    required: bool
    default: str


class TemplateRenderError(Exception):
    """Base class for failures while rendering a templated skill."""


class MissingTemplateVariableError(TemplateRenderError):
    """A required variable had no supplied value and no default."""

    def __init__(self, variable: TemplateVariable) -> None:
        self.variable = variable
        super().__init__(f"Missing required template variable '{variable.name}': {variable.prompt}")


class UnknownTemplatePlaceholderError(TemplateRenderError):
    """The body or a file referenced a `{{ placeholder }}` with no declared variable."""

    def __init__(self, placeholder: str) -> None:
        self.placeholder = placeholder
        super().__init__(f"Template references undeclared variable '{placeholder}'.")


def parse_template_variables(metadata: dict[str, Any] | None) -> list[TemplateVariable]:
    """Read the `variables` schema out of a skill's frontmatter metadata.

    Tolerant of malformed entries from synced/external content: anything without a usable string
    `name` is skipped rather than raising, so a bad row never breaks discovery or install.
    """
    if not metadata:
        return []
    raw = metadata.get("variables")
    if not isinstance(raw, list):
        return []

    variables: list[TemplateVariable] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        default = item.get("default", "")
        variables.append(
            TemplateVariable(
                name=name,
                prompt=str(item.get("prompt", "")),
                # Default to required unless a default is supplied or `required` is explicitly false.
                required=bool(item.get("required", "default" not in item)),
                default=str(default) if default is not None else "",
            )
        )
    return variables


def is_template(metadata: dict[str, Any] | None) -> bool:
    return len(parse_template_variables(metadata)) > 0


def resolve_bindings(variables: list[TemplateVariable], supplied: dict[str, str] | None) -> dict[str, str]:
    """Build the final {name: value} map, applying defaults and enforcing required variables."""
    supplied = supplied or {}
    bindings: dict[str, str] = {}
    for variable in variables:
        value = supplied.get(variable.name)
        if value is None or value == "":
            if variable.default:
                value = variable.default
            elif variable.required:
                raise MissingTemplateVariableError(variable)
            else:
                value = ""
        bindings[variable.name] = value
    return bindings


def render_text(text: str, bindings: dict[str, str]) -> str:
    """Substitute every `{{ name }}` placeholder, erroring on any undeclared name."""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in bindings:
            raise UnknownTemplatePlaceholderError(name)
        return bindings[name]

    return _PLACEHOLDER_RE.sub(_replace, text)


@dataclass(frozen=True)
class RenderedTemplate:
    body: str
    files: list[dict[str, str]]
    bindings: dict[str, str]


def render_template_skill(
    *,
    metadata: dict[str, Any] | None,
    body: str,
    files: list[dict[str, str]],
    supplied: dict[str, str] | None,
) -> RenderedTemplate:
    """Resolve user-supplied values against the declared variables and render body + files.

    Raises MissingTemplateVariableError when a required value is absent, and
    UnknownTemplatePlaceholderError when a placeholder has no matching declared variable.
    """
    variables = parse_template_variables(metadata)
    bindings = resolve_bindings(variables, supplied)

    rendered_files = [{**file, "content": render_text(file["content"], bindings)} for file in files]
    return RenderedTemplate(
        body=render_text(body, bindings),
        files=rendered_files,
        bindings=bindings,
    )
