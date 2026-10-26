"""Labels and annotations an alert's author sets on the rule, in the Prometheus sense.

Labels say who owns the alert and how urgent it is, such as `team` and `severity`, so a receiver can
route on them. Annotations carry context for the responder, such as `runbook_url`. Only annotations
take templates, because a label that changed with each check would make each check a new alert in
a receiver that keys on labels.
"""

from collections.abc import Collection, Mapping
from typing import Final
from urllib.parse import quote

import re2
import structlog

from products.alerts_platform.backend.facade.contracts import MessageLink
from products.alerts_platform.backend.facade.grouping import UNSTORABLE, encoded_length

logger = structlog.get_logger(__name__)

MAX_RULE_LABELS: Final = 20
_MAX_RULE_ANNOTATIONS: Final = 20
_MAX_NAME_LENGTH: Final = 128
# In bytes of the JSON a payload carries. A label is a short identifier, and an annotation can hold
# a paragraph of description.
_MAX_LABEL_VALUE_BYTES: Final = 256
_MAX_ANNOTATION_VALUE_BYTES: Final = 4096

# Prometheus's own pattern, so a label survives a hop through Alertmanager unchanged.
_NAME_PATTERN: Final = r"[a-zA-Z_][a-zA-Z0-9_]*"
_NAME: Final = re2.compile(_NAME_PATTERN)
# The platform adds these to every message. A rule that set them would hide what the platform says.
_RESERVED_PREFIX: Final = "posthog_"
_RESERVED_LABELS: Final = frozenset({"alertname"})

SUMMARY_ANNOTATION: Final = "summary"
DESCRIPTION_ANNOTATION: Final = "description"
RUNBOOK_ANNOTATION: Final = "runbook_url"
SEVERITY_LABEL: Final = "severity"
# Slack refuses an actions block with more than 25 buttons, and a message adds its own after these.
MAX_LINK_URL_CHARS: Final = 2000
_MAX_RULE_LINKS: Final = 5

_LABEL_REFERENCE: Final = re2.compile(rf"\s*\$labels\.({_NAME_PATTERN})\s*")
_VALUE_REFERENCE: Final = re2.compile(r"\s*\$value\s*")
# A host name and an optional port, and nothing a browser reads as the end of the host, such as `\`.
_LINK_HOST: Final = re2.compile(r"[a-zA-Z0-9.-]+(:[0-9]+)?")


class InvalidRuleMetadata(ValueError):
    pass


def validate_labels(labels: Mapping[str, str]) -> None:
    if len(labels) > MAX_RULE_LABELS:
        raise InvalidRuleMetadata(f"An alert can have at most {MAX_RULE_LABELS} labels.")
    for name, value in labels.items():
        _check_name(name, "label")
        if name in _RESERVED_LABELS:
            raise InvalidRuleMetadata(f"`{name}` is set by PostHog and cannot be a label.")
        _check_value(name, value, _MAX_LABEL_VALUE_BYTES)
        if "{{" in value:
            raise InvalidRuleMetadata(f"Label `{name}` cannot use a template. Only annotations can.")


def validate_annotations(annotations: Mapping[str, str], known_labels: Collection[str]) -> None:
    """`known_labels` are the names a template may reference: the grouping keys and the rule's labels."""
    if len(annotations) > _MAX_RULE_ANNOTATIONS:
        raise InvalidRuleMetadata(f"An alert can have at most {_MAX_RULE_ANNOTATIONS} annotations.")
    for name, value in annotations.items():
        _check_name(name, "annotation")
        _check_value(name, value, _MAX_ANNOTATION_VALUE_BYTES)
        for reference in _referenced_labels(name, value):
            if reference not in known_labels:
                raise InvalidRuleMetadata(
                    f"Annotation `{name}` uses `$labels.{reference}`, which is not a grouping key or a label of this alert."
                )
        if name.endswith("_url"):
            _check_link(name, value)


def _check_link(name: str, value: str) -> None:
    # A grouping key's value comes from query results. Templates may only follow the host, so data
    # can change which page a link opens but never which site.
    if not value.startswith("https://"):
        raise InvalidRuleMetadata(f"Annotation `{name}` must start with https://.")
    host = re2.split(r"[/?#]", value.removeprefix("https://"), maxsplit=1)[0]
    if not _LINK_HOST.fullmatch(host):
        raise InvalidRuleMetadata(f"Annotation `{name}` must name its host without a template.")


def render_annotations(
    annotations: Mapping[str, str], *, labels: Mapping[str, str], value: float | None
) -> dict[str, str]:
    """Each annotation with its templates filled in from one group's labels and value.

    A label the group does not carry renders as nothing, as in Prometheus. An annotation that no
    longer validates is left out rather than sent with its template showing.
    """
    rendered: dict[str, str] = {}
    for name, template in annotations.items():
        try:
            rendered[name] = _render(name, template, labels, value)
        except InvalidRuleMetadata:
            logger.warning("alerts_platform.annotation_not_rendered", annotation=name)
    return rendered


def links(annotations: Mapping[str, str]) -> tuple[MessageLink, ...]:
    """One link per `*_url` annotation, the runbook first, because that is where a responder starts.

    A link too long for every provider to send is left out, and so is any past the first few. A
    provider refuses the whole message when one button breaks its limits, which would lose the alert.
    """
    found = [
        MessageLink(label=_link_label(name), url=url)
        for name, url in annotations.items()
        if name.endswith("_url") and len(url) <= MAX_LINK_URL_CHARS
    ]
    found.sort(key=lambda link: link.label != _link_label(RUNBOOK_ANNOTATION))
    return tuple(found[:_MAX_RULE_LINKS])


def _link_label(name: str) -> str:
    return name.removesuffix("_url").replace("_", " ").strip().capitalize() or "Link"


def _render(name: str, template: str, labels: Mapping[str, str], value: float | None) -> str:
    # A label value comes from query results, so in a link it is quoted. It can then change which
    # page the link opens, but not add a query parameter or leave the path.
    quote_values = name.endswith("_url")
    parts: list[str] = []
    position = 0
    for start, end, body in _templates(name, template):
        reference = _reference(name, body)
        if reference is None:
            filled = "" if value is None else f"{value:g}"
        else:
            filled = labels.get(reference, "")
        parts.append(template[position:start])
        parts.append(quote(filled, safe="") if quote_values else filled)
        position = end
    parts.append(template[position:])
    return "".join(parts)


def _referenced_labels(name: str, value: str) -> list[str]:
    return [reference for _, _, body in _templates(name, value) if (reference := _reference(name, body)) is not None]


def _reference(name: str, body: str) -> str | None:
    """The label a template body names, or None for `$value`. Raises for anything else."""
    if label := _LABEL_REFERENCE.fullmatch(body):
        return label.group(1)
    if _VALUE_REFERENCE.fullmatch(body):
        return None
    raise InvalidRuleMetadata(
        f"Annotation `{name}` has an unsupported template `{{{{{body}}}}}`. "
        "Use {{ $labels.<name> }} or {{ $value }}."
    )


def _templates(name: str, value: str) -> list[tuple[int, int, str]]:
    """Each `{{ ... }}` as its start, its end past the closing braces, and the text between them."""
    # A scan with `find` reads each character once. An unclosed `{{` would otherwise slip past a
    # pattern that needs both delimiters, and skip every check on what follows it.
    templates: list[tuple[int, int, str]] = []
    position = 0
    while (start := value.find("{{", position)) != -1:
        end = value.find("}}", start + 2)
        if end == -1:
            raise InvalidRuleMetadata(f"Annotation `{name}` has a `{{{{` with no closing `}}}}`.")
        position = end + 2
        templates.append((start, position, value[start + 2 : end]))
    return templates


def _check_name(name: str, kind: str) -> None:
    # re2 cannot encode a lone surrogate, so it would raise instead of refusing the name.
    if len(name) > _MAX_NAME_LENGTH or UNSTORABLE.search(name) or not _NAME.fullmatch(name):
        raise InvalidRuleMetadata(
            f"`{name}` is not a valid {kind} name. Use letters, digits and underscores, "
            f"start with a letter or underscore, and use at most {_MAX_NAME_LENGTH} characters."
        )
    if name.startswith(_RESERVED_PREFIX):
        raise InvalidRuleMetadata(f"`{name}` uses the `{_RESERVED_PREFIX}` prefix, which PostHog reserves.")


def _check_value(name: str, value: str, max_bytes: int) -> None:
    if not value.strip():
        raise InvalidRuleMetadata(f"`{name}` needs a value.")
    if UNSTORABLE.search(value):
        raise InvalidRuleMetadata(f"The value of `{name}` has a character that cannot be stored.")
    if encoded_length(value) > max_bytes:
        raise InvalidRuleMetadata(f"The value of `{name}` is too long.")
