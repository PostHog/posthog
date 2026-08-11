from uuid import UUID


def task_comment_target_is_accessible(
    *, team_id: int, user_id: int | None, task_id: str | UUID, scope: str, item_id: str | None
) -> bool:
    from products.tasks.backend.facade.api import (
        task_comment_target_is_accessible as task_target_is_accessible,  # noqa: PLC0415  # Import lazily because generic comment imports must not load product models.
    )

    if scope != "desktop_canvas":
        return task_target_is_accessible(
            team_id=team_id,
            user_id=user_id,
            task_id=task_id,
            scope=scope,
            item_id=item_id,
        )
    if not task_target_is_accessible(
        team_id=team_id,
        user_id=user_id,
        task_id=task_id,
        scope="task",
        item_id=str(task_id),
    ):
        return False

    try:
        parsed_task_id = UUID(str(task_id))
    except ValueError:
        return False
    if not item_id:
        return False

    from products.canvas.backend.comment_access import (
        canvas_belongs_to_task,  # noqa: PLC0415  # Import lazily because non-canvas comments do not need Canvas models.
    )

    return canvas_belongs_to_task(
        team_id=team_id,
        user_id=user_id,
        canvas_id=item_id,
        task_id=parsed_task_id,
    )
