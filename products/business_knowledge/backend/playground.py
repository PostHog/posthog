from __future__ import annotations

from typing import Any

from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.facade.contracts import CreatedTaskDTO

from .models import PlaygroundChat, PlaygroundTurn
from .sandbox import _title_for, load_sandbox_run, start_sandbox_run


def create_playground_chat(*, team: Team, user: User) -> PlaygroundChat:
    return PlaygroundChat.objects.create(team=team, created_by=user, title="")


def serialize_playground_chat_list_item(chat: PlaygroundChat) -> dict[str, Any]:
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
    }


def serialize_playground_chat(*, chat: PlaygroundChat, user_id: int) -> dict[str, Any]:
    turns = PlaygroundTurn.objects.filter(chat=chat).order_by("position")
    return {
        **serialize_playground_chat_list_item(chat),
        "turns": [serialize_playground_turn(turn, user_id=user_id) for turn in turns],
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

    start_sandbox_run(team=team, user_id=user_id, question=question, on_admitted=record_turn)
    return serialize_playground_chat(chat=chat, user_id=user_id)
