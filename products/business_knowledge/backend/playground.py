from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.facade.contracts import CreatedTaskDTO

from .models import PlaygroundChat, PlaygroundTurn
from .sandbox import (
    SandboxPollStatus,
    SandboxRunInProgress,
    _title_for,
    load_sandbox_run,
    open_sandbox_task_ids,
    start_sandbox_run,
)


def create_playground_chat(*, team: Team, user: User) -> PlaygroundChat:
    return PlaygroundChat.objects.create(team=team, created_by=user, title="")


def serialize_playground_chat_list_item(chat: PlaygroundChat, *, has_open_turn: bool) -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "has_open_turn": has_open_turn,
    }


def serialize_playground_chat_list(chats: Iterable[PlaygroundChat], *, team_id: int, user_id: int) -> list[dict]:
    chats = list(chats)
    open_task_ids = open_sandbox_task_ids(team_id=team_id, user_id=user_id)
    open_chat_ids = (
        set(
            PlaygroundTurn.objects.for_team(team_id)
            .filter(chat_id__in=[chat.id for chat in chats], task_id__in=open_task_ids)
            .values_list("chat_id", flat=True)
        )
        if open_task_ids and chats
        else set()
    )
    return [serialize_playground_chat_list_item(chat, has_open_turn=chat.id in open_chat_ids) for chat in chats]


def serialize_playground_chat(*, chat: PlaygroundChat, user_id: int) -> dict[str, Any]:
    turns = PlaygroundTurn.objects.filter(chat=chat).order_by("position")
    serialized_turns = [serialize_playground_turn(turn, user_id=user_id) for turn in turns]
    has_open_turn = any(
        turn["run"] is not None and turn["run"]["status"] == SandboxPollStatus.RUNNING for turn in serialized_turns
    )
    return {
        **serialize_playground_chat_list_item(chat, has_open_turn=has_open_turn),
        "turns": serialized_turns,
    }


def serialize_playground_turn(turn: PlaygroundTurn, *, user_id: int) -> dict[str, Any]:
    run = load_sandbox_run(task_id=str(turn.task_id), team_id=turn.team_id, user_id=user_id)
    return {
        "id": turn.id,
        "question": turn.question,
        "task_id": turn.task_id,
        "position": turn.position,
        "run": run,
        "error": None if run is not None else "Couldn't load this answer. Try again.",
    }


def ask_playground_chat(*, chat: PlaygroundChat, team: Team, user_id: int, question: str) -> dict[str, Any]:
    def admit_one_run_per_chat() -> None:
        # The chat row lock serializes asks in this chat. Other chats of the same person run in parallel.
        PlaygroundChat.objects.for_team(chat.team_id).select_for_update().filter(id=chat.id).first()
        open_task_ids = open_sandbox_task_ids(team_id=chat.team_id, user_id=user_id)
        if (
            open_task_ids
            and PlaygroundTurn.objects.for_team(chat.team_id).filter(chat=chat, task_id__in=open_task_ids).exists()
        ):
            raise SandboxRunInProgress()

    def record_turn(created: CreatedTaskDTO) -> None:
        last = PlaygroundTurn.objects.filter(chat=chat).order_by("-position").values_list("position", flat=True).first()
        PlaygroundTurn.objects.create(
            team_id=chat.team_id,
            chat=chat,
            question=question,
            task_id=created.task_id,
            position=0 if last is None else last + 1,
        )
        if not chat.title:
            chat.title = _title_for(question)
            chat.save(update_fields=["title", "updated_at"])
        else:
            chat.save(update_fields=["updated_at"])

    start_sandbox_run(
        team=team,
        user_id=user_id,
        question=question,
        admit=admit_one_run_per_chat,
        on_admitted=record_turn,
    )
    return serialize_playground_chat(chat=chat, user_id=user_id)
