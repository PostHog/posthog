from uuid import UUID


def visible_task_canvas_ids(*, team_id: int, task_id: UUID, user_id: int | None) -> list[str]:
    from products.canvas.backend.comment_access import (  # noqa: PLC0415 — keeps the shared comment model importable without loading the Canvas product
        visible_canvas_ids_for_task,
    )

    return visible_canvas_ids_for_task(team_id=team_id, task_id=task_id, user_id=user_id)
