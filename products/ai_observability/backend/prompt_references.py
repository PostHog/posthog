import re

from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.llm_prompt import normalize_prompt_to_string

from products.ai_observability.backend.models.llm_prompt import LLMPrompt, LLMPromptDependency

# Both charsets are enforced at write time (validate_prompt_name_value,
# validate_prompt_label_name_value in posthog/api/llm_prompt_serializers.py),
# so a tag can always be parsed without escaping. Widening either charset
# requires revisiting this grammar.
# The length bounds mirror the LLMPromptDependency columns (name varchar(255),
# label varchar(128)) and the int4 range for version, so an oversized value
# makes the tag plain text instead of failing the row insert and rolling back
# the write that carried it. Versions start at 1 and have no leading zeros,
# so a selector that can never match a version is plain text too.
PROMPT_REFERENCE_REGEX = re.compile(
    r"@@@prompt:"
    r"name=(?P<name>[A-Za-z0-9_-]{1,255})\|"
    r"(?:version=(?P<version>[1-9][0-9]{0,8})|label=(?P<label>[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?))"
    r"@@@"
)

MAX_PROMPT_REFERENCES = 20


@frozen
class PromptReference:
    """One `@@@prompt:...@@@` tag inside a prompt's text.

    Exactly one of `version` and `label` is set: a version reference is pinned
    forever, a label reference follows wherever the label points.
    """

    name: str
    version: int | None
    label: str | None

    def __post_init__(self) -> None:
        if (self.version is None) == (self.label is None):
            raise ValueError("A prompt reference has exactly one of version and label.")


def parse_prompt_references(text: str) -> list[PromptReference]:
    """Extract references in order of appearance, duplicates included."""
    references = []
    for match in PROMPT_REFERENCE_REGEX.finditer(text):
        version = match.group("version")
        references.append(
            PromptReference(
                name=match.group("name"),
                version=int(version) if version is not None else None,
                label=match.group("label"),
            )
        )
    return references


def record_prompt_references(prompt: LLMPrompt) -> list[LLMPromptDependency]:
    """Persist the references found in a version's content.

    Call once per version row, inside the transaction that creates it, so the
    dependency rows share the version row's immutability and atomicity.
    """
    references = parse_prompt_references(normalize_prompt_to_string(prompt.prompt))
    if not references:
        return []
    # A tag repeated in the content is one dependency edge.
    unique_references = list(dict.fromkeys(references))
    # Raised from here so create, publish, and duplicate all share the one
    # check; the surrounding transaction rolls the version row back with it.
    if len(unique_references) > MAX_PROMPT_REFERENCES:
        raise serializers.ValidationError(
            f"A prompt can reference at most {MAX_PROMPT_REFERENCES} other prompts. "
            "Remove some references and try again.",
            code="too_many_references",
        )
    return LLMPromptDependency.objects.bulk_create(
        [
            LLMPromptDependency(
                team_id=prompt.team_id,
                prompt=prompt,
                parent_name=prompt.name,
                child_name=reference.name,
                child_version=reference.version,
                child_label=reference.label,
            )
            for reference in unique_references
        ]
    )
