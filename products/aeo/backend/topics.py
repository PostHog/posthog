"""Topic edits across the prompt set: rename a topic, merge one into another, remove one, or set one on chosen prompts.

A topic is a label on each prompt, and topics that differ only in letter case are one topic. A rename, a merge
or a removal changes the label everywhere it appears: on every prompt that has it, archived prompts included,
and on the past checks that ran with it. So the reports keep one history per topic, under its new name.
Setting a topic on chosen prompts changes only those prompts, and their past checks keep the topic they ran
with, the same as an edit of one prompt.

No topic edit adds a prompt version. A version records the prompt's text, and the topic is not part of it.

Every edit first locks the project's config row, the same row an import that turns prompts on locks, so two
edits never read a topic name the other one is about to change. Prompt rows are then locked in `prompt_hash`
order, the order an import locks them in, so an edit and an import never deadlock.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.db.models import Min
from django.db.models.functions import Collate
from django.utils import timezone

from products.aeo.backend import prompt_limit
from products.aeo.backend.facade.contracts import (
    PROMPT_TOPIC_MAX_LENGTH,
    PromptNotFoundError,
    PromptTopicChange,
    PromptTopicConflictError,
    PromptTopicError,
    PromptTopicNotFoundError,
    PromptUpdateError,
)
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt
from products.aeo.backend.seeding import normalize_prompt
from products.aeo.backend.stored_results import bump_data_version_on_commit


def clean_topic(topic: str) -> str:
    return normalize_prompt(topic)[:PROMPT_TOPIC_MAX_LENGTH]


def rename_topic(team_id: int, topic: str, new_topic: str) -> PromptTopicChange:
    """A new name that differs only in letter case is allowed, so a rename can fix the spelling of a topic.
    Raises PromptTopicNotFoundError, and PromptTopicConflictError when another topic already has the name."""
    old, new = _named(topic), _named(new_topic)
    if old == new:
        raise PromptTopicError("Enter a different name.")
    with transaction.atomic():
        _lock_topics(team_id)
        # Archived prompts count, because a rename also relabels them and their checks.
        if old.lower() != new.lower() and _topic_exists(team_id, new):
            raise PromptTopicConflictError(f'A topic named "{new}" already exists. Merge the topics instead.')
        return _relabel(team_id, old, new)


def merge_topics(team_id: int, topic: str, into_topic: str) -> PromptTopicChange:
    """The prompts of `topic` take `into_topic` as it is spelled now. Raises PromptTopicNotFoundError when
    either topic is missing, and PromptTopicError when they are the same topic."""
    source, target = _named(topic), _named(into_topic)
    if source.lower() == target.lower():
        raise PromptTopicError("Choose a different topic to merge into.")
    with transaction.atomic():
        _lock_topics(team_id)
        label = _current_label(team_id, target)
        if label is None:
            raise PromptTopicNotFoundError(f'No prompt has the topic "{target}".')
        return _relabel(team_id, source, label)


def remove_topic(team_id: int, topic: str) -> PromptTopicChange:
    """The prompts of `topic` are left with no topic. Raises PromptTopicNotFoundError."""
    with transaction.atomic():
        _lock_topics(team_id)
        return _relabel(team_id, _named(topic), "")


def set_topic(team_id: int, prompt_ids: list[uuid.UUID], topic: str) -> PromptTopicChange:
    """An empty topic removes the topic from the prompts. A topic that matches an existing one in another
    letter case takes its spelling, so the label stays the same across the set. Raises PromptNotFoundError
    when an id is not in the set, and PromptUpdateError when a prompt is archived. Nothing changes then."""
    wanted = set(prompt_ids)
    new = clean_topic(topic)
    with transaction.atomic():
        _lock_topics(team_id)
        prompts = AEOPrompt.objects.for_team(team_id).filter(id__in=wanted)
        archived = [
            row.archived_at is not None
            for row in prompts.select_for_update().order_by("prompt_hash").only("archived_at", "prompt_hash")
        ]
        if len(archived) != len(wanted):
            raise PromptNotFoundError("Some of the prompts aren't in this project.")
        if any(archived):
            raise PromptUpdateError("Restore archived prompts before you change their topic.")
        label = (_current_label(team_id, new) or new) if new else ""
        updated = prompts.update(topic=label, updated_at=timezone.now())
        # A bulk update sends no post_save signal, so the stored results need the bump here.
        bump_data_version_on_commit(team_id)
    return PromptTopicChange(prompts=updated, checks=0)


def _named(topic: str) -> str:
    cleaned = clean_topic(topic)
    if not cleaned:
        raise PromptTopicError("Enter a topic name.")
    return cleaned


def _lock_topics(team_id: int) -> None:
    prompt_limit.lock_project(team_id)


def _topic_exists(team_id: int, topic: str) -> bool:
    return AEOPrompt.objects.for_team(team_id).filter(topic__iexact=topic).exists()


def _current_label(team_id: int, topic: str) -> str | None:
    """How a topic is spelled on the prompts that are not archived, or None when none has it. Collated the
    same way as the topic list, so both pick the same spelling of a topic with mixed letter case."""
    return (
        AEOPrompt.objects.for_team(team_id)
        .filter(archived_at__isnull=True, topic__iexact=topic)
        .aggregate(label=Min(Collate("topic", "C")))["label"]
    )


def _relabel(team_id: int, old: str, new: str) -> PromptTopicChange:
    matching = AEOPrompt.objects.for_team(team_id).filter(topic__iexact=old)
    ids = list(matching.select_for_update().order_by("prompt_hash").values_list("id", flat=True))
    if not ids:
        raise PromptTopicNotFoundError(f'No prompt has the topic "{old}".')
    prompts = AEOPrompt.objects.for_team(team_id).filter(id__in=ids).update(topic=new, updated_at=timezone.now())
    # Rows that already read `new` are left alone, so a check is rewritten only when its label changes.
    checks = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(prompt_topic__iexact=old)
        .exclude(prompt_topic=new)
        .update(prompt_topic=new)
    )
    # A bulk update sends no post_save signal, so the stored results need the bump here.
    bump_data_version_on_commit(team_id)
    return PromptTopicChange(prompts=prompts, checks=checks)
