"""Labels and annotations an alert's author sets on the rule, in the Prometheus sense.

Labels say who owns the alert and how urgent it is, such as `team` and `severity`, so a receiver can
route on them. Annotations carry context for the responder, such as `runbook_url`. Only annotations
take templates, because a label that changed with each check would make each check a new alert in
a receiver that keys on labels.
"""

import json
from collections.abc import Collection, Mapping
from typing import Final

import re2

MAX_RULE_LABELS: Final = 20
MAX_RULE_ANNOTATIONS: Final = 20
MAX_NAME_LENGTH: Final = 128
# In bytes of the JSON a payload carries. A label is a short identifier, and an annotation can hold
# a paragraph of description.
MAX_LABEL_VALUE_BYTES: Final = 256
MAX_ANNOTATION_VALUE_BYTES: Final = 4096

# Prometheus's own pattern, so a label survives a hop through Alertmanager unchanged.
_NAME: Final = re2.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
# The platform adds these to every message. A rule that set them would hide what the platform says.
RESERVED_PREFIX: Final = "posthog_"
RESERVED_LABELS: Final = frozenset({"alertname"})

URL_SUFFIX: Final = "_url"

_LABEL_REFERENCE: Final = re2.compile(r"\s*\$labels\.([a-zA-Z_][a-zA-Z0-9_]*)\s*")
_VALUE_REFERENCE: Final = re2.compile(r"\s*\$value\s*")


class InvalidRuleMetadata(ValueError):
    pass


def validate_labels(labels: Mapping[str, str]) -> None:
    if len(labels) > MAX_RULE_LABELS:
        raise InvalidRuleMetadata(f"An alert can have at most {MAX_RULE_LABELS} labels.")
    for name, value in labels.items():
        _check_name(name, "label")
        if name in RESERVED_LABELS:
            raise InvalidRuleMetadata(f"`{name}` is set by PostHog and cannot be a label.")
        _check_value(name, value, MAX_LABEL_VALUE_BYTES)
        if "{{" in value:
            raise InvalidRuleMetadata(f"Label `{name}` cannot use a template. Only annotations can.")


def validate_annotations(annotations: Mapping[str, str], known_labels: Collection[str]) -> None:
    """`known_labels` are the names a template may reference: the grouping keys and the rule's labels."""
    if len(annotations) > MAX_RULE_ANNOTATIONS:
        raise InvalidRuleMetadata(f"An alert can have at most {MAX_RULE_ANNOTATIONS} annotations.")
    for name, value in annotations.items():
        _check_name(name, "annotation")
        _check_value(name, value, MAX_ANNOTATION_VALUE_BYTES)
        for reference in referenced_labels(name, value):
            if reference not in known_labels:
                raise InvalidRuleMetadata(
                    f"Annotation `{name}` uses `$labels.{reference}`, which is not a grouping key or a label of this alert."
                )
        # A template can only fill in the path, so a link can never become another scheme.
        if name.endswith(URL_SUFFIX) and not value.startswith("https://"):
            raise InvalidRuleMetadata(f"Annotation `{name}` must start with https://.")


def referenced_labels(name: str, value: str) -> list[str]:
    """The label names a template references. Raises for anything but `$labels.<name>` and `$value`."""
    references: list[str] = []
    for body in _template_bodies(name, value):
        if label := _LABEL_REFERENCE.fullmatch(body):
            references.append(label.group(1))
        elif not _VALUE_REFERENCE.fullmatch(body):
            raise InvalidRuleMetadata(
                f"Annotation `{name}` has an unsupported template `{{{{{body}}}}}`. "
                "Use {{ $labels.<name> }} or {{ $value }}."
            )
    return references


def _template_bodies(name: str, value: str) -> list[str]:
    # A scan with `find` reads each character once. An unclosed `{{` would otherwise slip past a
    # pattern that needs both delimiters, and skip every check on what follows it.
    bodies: list[str] = []
    position = 0
    while (start := value.find("{{", position)) != -1:
        end = value.find("}}", start + 2)
        if end == -1:
            raise InvalidRuleMetadata(f"Annotation `{name}` has a `{{{{` with no closing `}}}}`.")
        bodies.append(value[start + 2 : end])
        position = end + 2
    return bodies


def _check_name(name: str, kind: str) -> None:
    if len(name) > MAX_NAME_LENGTH or not _NAME.fullmatch(name):
        raise InvalidRuleMetadata(
            f"`{name}` is not a valid {kind} name. Use letters, digits and underscores, "
            f"start with a letter or underscore, and keep it under {MAX_NAME_LENGTH} characters."
        )
    if name.startswith(RESERVED_PREFIX):
        raise InvalidRuleMetadata(f"`{name}` uses the `{RESERVED_PREFIX}` prefix, which PostHog reserves.")


def _check_value(name: str, value: str, max_bytes: int) -> None:
    if not value.strip():
        raise InvalidRuleMetadata(f"`{name}` needs a value.")
    if len(json.dumps(value)) - 2 > max_bytes:
        raise InvalidRuleMetadata(f"The value of `{name}` is too long.")
