from uuid import UUID

from posthog.models.comment.comment import CANVAS_COMMENT_SCOPES


def task_comment_target_is_accessible(
    *,
    team_id: int,
    user_id: int | None,
    task_id: str | UUID | None,
    scope: str,
    item_id: str | None,
    sandbox: bool = False,
    sandbox_task_id: UUID | None = None,
) -> bool:
    if scope not in CANVAS_COMMENT_SCOPES:
        if not task_id:
            return False
        from products.tasks.backend.facade.api import (
            task_accessible_for_run_view,  # noqa: PLC0415  # Import lazily because generic comment imports must not load product models.
            task_comment_target_is_accessible as task_target_is_accessible,  # noqa: PLC0415  # Import lazily because generic comment imports must not load product models.
        )

        if not task_target_is_accessible(
            team_id=team_id,
            user_id=user_id,
            task_id=task_id,
            scope=scope,
            item_id=item_id,
        ):
            return False
        return not sandbox or task_accessible_for_run_view(
            task_id,
            team_id,
            user_id,
            sandbox_request=True,
            sandbox_task_id=sandbox_task_id,
        )

    if not item_id:
        return False
    parsed_task_id = None
    if task_id:
        try:
            parsed_task_id = UUID(str(task_id))
        except ValueError:
            return False

    from products.canvas.backend.facade.access import (
        canvas_comments_accessible,  # noqa: PLC0415  # Import lazily because non-canvas comments do not need Canvas models.
    )

    return canvas_comments_accessible(
        team_id=team_id,
        user_id=user_id,
        canvas_id=item_id,
        task_id=parsed_task_id,
        sandbox=sandbox,
    )
