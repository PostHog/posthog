import re
from collections import Counter
from typing import Any

from django.db import InterfaceError, OperationalError
from django.db.models import Q

from rest_framework import serializers

from posthog.dataclasses import frozen
from posthog.llm_prompt import MAX_PROMPT_PAYLOAD_BYTES, normalize_prompt_to_string
from posthog.models.team.team import Team
from posthog.storage.llm_prompt_cache import get_prompt_by_name_from_cache

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
# Incoming references are unbounded (any number of prompts can reference one
# partial), so surfaces listing them cap the result. Existence checks stay
# correct: over the cap still means "referenced".
MAX_ACTIVE_REFERENCE_RESULTS = 100


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
    return sorted({reference["name"] for reference in get_active_references_to(team_id, child_name)})


def get_active_references_to(team_id: int, child_name: str) -> list[dict[str, Any]]:
    """Active incoming references with the selector each parent used.

    `label` set means the parent follows that label of this prompt, so moving
    it propagates; `version` set means the parent pinned that version and
    nothing propagates to it.
    """
    rows = (
        LLMPromptDependency.objects.filter(team_id=team_id, child_name=child_name, prompt__deleted=False)
        .filter(Q(prompt__is_latest=True) | Q(prompt__labels__isnull=False))
        .exclude(parent_name=child_name)
        .values_list("parent_name", "child_label", "child_version")
        .distinct()
        .order_by("parent_name", "child_label", "child_version")[:MAX_ACTIVE_REFERENCE_RESULTS]
    )
    return [{"name": name, "label": label, "version": version} for name, label, version in rows]


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

    Must run inside the transaction that writes the version row: the target
    lookups take row locks so a concurrent archive or label change on a
    referenced prompt serializes with this validation instead of racing it.
    Targets are processed in sorted order so concurrent publishers acquire
    locks in the same order.
    """
    text = normalize_prompt_to_string(prompt_payload)
    all_references = parse_prompt_references(text)
    references = sorted(set(all_references), key=lambda r: (r.name, r.version or 0, r.label or ""))
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

    # True assembled size: the tags are replaced by content at resolution,
    # so their bytes leave the total.
    tag_bytes = sum(len(match.group(0).encode("utf-8")) for match in PROMPT_REFERENCE_REGEX.finditer(text))
    assembled_bytes = len(text.encode("utf-8")) - tag_bytes
    for reference in references:
        if reference.name == prompt_name:
            raise _reference_error(
                "A prompt cannot reference itself. Remove the reference to "
                f"'{reference.name}' or point it at another prompt.",
                "self_reference",
            )

        if reference.version is not None:
            target = (
                LLMPrompt.objects.select_for_update()
                .filter(team_id=team_id, name=reference.name, version=reference.version, deleted=False)
                .first()
            )
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
            # Two steps in label-then-prompt order, matching set_prompt_label
            # and archive_prompt, so no pair of paths locks the same two rows
            # in opposite orders.
            label = (
                LLMPromptLabel.objects.select_for_update()
                .filter(team_id=team_id, prompt_name=reference.name, name=reference.label)
                .first()
            )
            locked_target = (
                LLMPrompt.objects.select_for_update().filter(pk=label.prompt_id, team_id=team_id).first()
                if label is not None
                else None
            )
            if locked_target is None or locked_target.deleted:
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
            target = locked_target

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


@frozen
class PromptReferenceResolutionError(Exception):
    """A fetched prompt's reference cannot be spliced in.

    `missing` distinguishes "the referenced prompt/version/label is gone"
    (a 404 for the caller) from "the referenced content is in a state
    validation normally prevents", e.g. nested references or an oversized
    assembly reached through a raced label move (a 409). `unavailable` means
    the reference could not be checked at all (a 503): the caller should
    retry, not edit their prompt.
    """

    reference_name: str
    message: str
    missing: bool
    unavailable: bool = False


def _confirm_reference_missing(team_id: int, name: str, version: str | None, label: str | None) -> bool:
    """Distinguish a genuinely absent reference target from a database outage.

    The cached read path deliberately degrades transient database errors to
    None. Served raw, that tells SDK callers the referenced prompt "no longer
    exists" during an outage. This direct check runs only on the miss path,
    so the warm fetch stays cache-only.
    """
    try:
        if version is not None:
            return not LLMPrompt.objects.filter(
                team_id=team_id, name=name, version=int(version), deleted=False
            ).exists()
        return not LLMPromptLabel.objects.filter(
            team_id=team_id, prompt_name=name, name=label, prompt__deleted=False
        ).exists()
    except (OperationalError, InterfaceError):
        return False


def assemble_prompt_payload(team: Team, payload: dict[str, Any]) -> dict[str, Any]:
    """Splice referenced prompts' content into a fetched payload.

    Each referenced prompt resolves through the same cached read path as the
    payload itself, so staleness stays inside the documented cache TTLs and a
    warm fetch costs one cache read per referenced prompt. Depth is one level
    by validation, so there is no recursion. Raises
    PromptReferenceResolutionError instead of ever returning a payload with a
    raw tag or a hole where referenced content should be.
    """
    content = payload.get("prompt")
    if not isinstance(content, str) or not PROMPT_REFERENCE_REGEX.search(content):
        return {**payload, "resolved_references": []}

    resolved: list[dict[str, Any]] = []
    # Publish validation caps unique references, not occurrences: a 1 MB body
    # can hold ~35k copies of one small tag whose label later moves to a large
    # version. Memoizing bounds the cache reads to the unique references, and
    # the running size check aborts before a large assembly is materialized,
    # so a fetch never allocates more than the payload cap.
    memoized: dict[tuple[str, str | None, str | None], str] = {}
    # Running total of the true assembled size: each replacement removes the
    # tag's bytes and adds the spliced content's bytes.
    assembled_bytes = len(content.encode("utf-8"))

    def _splice(match: re.Match[str]) -> str:
        nonlocal assembled_bytes
        name = match.group("name")
        version = match.group("version")
        label = match.group("label")
        key = (name, version, label)
        child_content = memoized.get(key)
        if child_content is None:
            child = get_prompt_by_name_from_cache(
                team, name, int(version) if version is not None else None, label=label
            )
            if child is None:
                if not _confirm_reference_missing(team.id, name, version, label):
                    raise PromptReferenceResolutionError(
                        reference_name=name,
                        message=f"Couldn't load the referenced prompt '{name}' right now. Try again.",
                        missing=False,
                        unavailable=True,
                    )
                selector = f"version {version}" if version is not None else f"label '{label}'"
                raise PromptReferenceResolutionError(
                    reference_name=name,
                    message=f"This prompt references '{name}' at {selector}, which no longer exists.",
                    missing=True,
                )
            child_content = child.get("prompt")
            if not isinstance(child_content, str):
                raise PromptReferenceResolutionError(
                    reference_name=name,
                    message=f"The referenced prompt '{name}' is not plain text and cannot be spliced in.",
                    missing=False,
                )
            if PROMPT_REFERENCE_REGEX.search(child_content):
                raise PromptReferenceResolutionError(
                    reference_name=name,
                    message=f"The referenced prompt '{name}' contains references of its own and cannot be spliced in.",
                    missing=False,
                )
            memoized[key] = child_content
            resolved.append({"name": name, "version": child["version"], "label": label})
        assembled_bytes += len(child_content.encode("utf-8")) - len(match.group(0).encode("utf-8"))
        if assembled_bytes > MAX_PROMPT_PAYLOAD_BYTES:
            raise PromptReferenceResolutionError(
                reference_name=payload["name"],
                message=(
                    f"The prompt with all referenced content included exceeds {MAX_PROMPT_PAYLOAD_BYTES} bytes. "
                    "Shorten the prompt or its referenced prompts."
                ),
                missing=False,
            )
        return child_content

    assembled = PROMPT_REFERENCE_REGEX.sub(_splice, content)
    return {**payload, "prompt": assembled, "resolved_references": resolved}
