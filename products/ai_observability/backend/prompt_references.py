import re
from collections import Counter
from typing import Any

from django.db.models import Q

from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.llm_prompt import MAX_PROMPT_PAYLOAD_BYTES, normalize_prompt_to_string

from products.ai_observability.backend.models.llm_prompt import LLMPrompt, LLMPromptDependency, LLMPromptLabel

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


def get_active_referencing_parent_names(team_id: int, child_name: str) -> list[str]:
    """Prompts whose latest or labeled version references `child_name`.

    A reference only held by an old, unlabeled version does not count: nothing
    can fetch that version through a pointer, so it neither blocks archiving
    nor blocks the referenced prompt from gaining references of its own.
    Self-referencing rows are excluded: validation rejects them now, but rows
    recorded before validation existed must not let a prompt block its own
    archival.
    """
    return sorted(
        LLMPromptDependency.objects.filter(team_id=team_id, child_name=child_name, prompt__deleted=False)
        .filter(Q(prompt__is_latest=True) | Q(prompt__labels__isnull=False))
        .exclude(parent_name=child_name)
        .values_list("parent_name", flat=True)
        .distinct()
    )


def get_active_parents_referencing_label(team_id: int, prompt_name: str, label_name: str) -> list[str]:
    """Prompts whose latest or labeled version references `prompt_name` through this label."""
    return sorted(
        LLMPromptDependency.objects.filter(
            team_id=team_id, child_name=prompt_name, child_label=label_name, prompt__deleted=False
        )
        .filter(Q(prompt__is_latest=True) | Q(prompt__labels__isnull=False))
        .exclude(parent_name=prompt_name)
        .values_list("parent_name", flat=True)
        .distinct()
    )


def _reference_error(message: str, code: str) -> serializers.ValidationError:
    return serializers.ValidationError(message, code=code)


def validate_prompt_references(team_id: int, *, prompt_name: str, prompt_payload: Any) -> None:
    """Reject content whose references cannot resolve, before a version row is written.

    Raises DRF ValidationError so every write path (create, publish, duplicate)
    surfaces the same 400. Depth is capped at one level: a prompt that contains
    references cannot itself be referenced, checked in both directions here.
    """
    text = normalize_prompt_to_string(prompt_payload)
    all_references = parse_prompt_references(text)
    references = list(dict.fromkeys(all_references))
    if not references:
        return

    # Resolution splices content at every occurrence, so the assembled-size
    # check has to weigh a repeated tag once per occurrence.
    occurrence_counts = Counter(all_references)

    if len(references) > MAX_PROMPT_REFERENCES:
        raise _reference_error(
            f"A prompt can reference at most {MAX_PROMPT_REFERENCES} other prompts. "
            "Remove some references and try again.",
            "too_many_references",
        )

    referenced_by = get_active_referencing_parent_names(team_id, prompt_name)
    if referenced_by:
        raise _reference_error(
            f"This prompt is referenced by {', '.join(referenced_by)}. "
            "A referenced prompt cannot contain references of its own.",
            "referenced_prompt_cannot_reference",
        )

    assembled_bytes = len(text.encode("utf-8"))
    for reference in references:
        if reference.name == prompt_name:
            raise _reference_error(
                "A prompt cannot reference itself. Remove the reference to "
                f"'{reference.name}' or point it at another prompt.",
                "self_reference",
            )

        if reference.version is not None:
            target = LLMPrompt.objects.filter(
                team_id=team_id, name=reference.name, version=reference.version, deleted=False
            ).first()
            if target is None:
                exists = LLMPrompt.objects.filter(team_id=team_id, name=reference.name, deleted=False).exists()
                if not exists:
                    raise _reference_error(
                        f"The referenced prompt '{reference.name}' does not exist. "
                        "Create it first or remove the reference.",
                        "reference_not_found",
                    )
                raise _reference_error(
                    f"Prompt '{reference.name}' has no version {reference.version}. "
                    "Pin an existing version or use a label.",
                    "reference_version_not_found",
                )
        else:
            label = (
                LLMPromptLabel.objects.filter(team_id=team_id, prompt_name=reference.name, name=reference.label)
                .select_related("prompt")
                .first()
            )
            if label is None or label.prompt.deleted:
                exists = LLMPrompt.objects.filter(team_id=team_id, name=reference.name, deleted=False).exists()
                if not exists:
                    raise _reference_error(
                        f"The referenced prompt '{reference.name}' does not exist. "
                        "Create it first or remove the reference.",
                        "reference_not_found",
                    )
                raise _reference_error(
                    f"Prompt '{reference.name}' has no label '{reference.label}'. "
                    "Create the label first or pin a version instead.",
                    "reference_label_not_found",
                )
            target = label.prompt

        if not isinstance(target.prompt, str):
            raise _reference_error(
                f"Prompt '{reference.name}' cannot be referenced because its content is not plain text.",
                "reference_not_text",
            )

        if parse_prompt_references(target.prompt):
            raise _reference_error(
                f"Prompt '{reference.name}' contains references of its own. "
                "Referenced prompts cannot contain references.",
                "nested_reference",
            )

        assembled_bytes += len(target.prompt.encode("utf-8")) * occurrence_counts[reference]

    # Best effort for label references: a label can later move to a bigger
    # version. The fetch path enforces the same cap when it assembles.
    if assembled_bytes > MAX_PROMPT_PAYLOAD_BYTES:
        raise _reference_error(
            f"The prompt with all referenced content included exceeds {MAX_PROMPT_PAYLOAD_BYTES} bytes. "
            "Shorten the prompt or its referenced prompts.",
            "assembled_too_large",
        )


def record_prompt_references(prompt: LLMPrompt) -> list[LLMPromptDependency]:
    """Persist the references found in a version's content.

    Call once per version row, inside the transaction that creates it, so the
    dependency rows share the version row's immutability and atomicity. The
    content was validated by validate_prompt_references before the row was
    written, so this only records.
    """
    references = parse_prompt_references(normalize_prompt_to_string(prompt.prompt))
    if not references:
        return []
    # A tag repeated in the content is one dependency edge.
    unique_references = list(dict.fromkeys(references))
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
