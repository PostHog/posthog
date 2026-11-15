from django.apps import AppConfig


class CanvasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.canvas.backend"
    label = "canvas"
    verbose_name = "Canvas"

    def ready(self) -> None:
        # Registers the artifact-delivery configuration system checks and the
        # search-index signal receivers.
        from typing import Any  # noqa: PLC0415

        from django.db.models import QuerySet  # noqa: PLC0415

        from rest_framework.exceptions import PermissionDenied, ValidationError  # noqa: PLC0415

        from posthog.api.file_system.deletion import (  # noqa: PLC0415
            DeletionContext,
            RestoreContext,
            register_file_system_type,
            register_pre_delete_hook,
            register_pre_restore_hook,
        )
        from posthog.api.file_system.visibility import register_file_system_visibility_filter  # noqa: PLC0415
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        from products.canvas.backend import checks, search_sync  # noqa: F401, PLC0415
        from products.canvas.backend.models import Canvas  # noqa: PLC0415

        register_mixin_model("canvas", Canvas)
        register_file_system_type(
            "canvas",
            "canvas",
            "Canvas",
            soft_delete_field="deleted",
            undo_message="Send POST /api/projects/@current/file_system/undo_delete/ with this type and ref.",
        )

        def _filter_rows(rows: QuerySet, request: Any, project_id: int) -> QuerySet:
            # The visibility module reaches the tasks product and the LLM clients, so it loads on first use
            # rather than in every process at startup: keeps the heavy dep off django.setup().
            from products.canvas.backend.logic import visibility  # noqa: PLC0415

            return visibility.filter_file_system_rows(rows, request, project_id)

        def _authorize_delete(context: DeletionContext, canvas: Canvas) -> None:
            from posthog.oauth_provenance import is_sandbox_oauth_request  # noqa: PLC0415

            from products.canvas.backend.logic import visibility  # noqa: PLC0415

            # A file system row carries no channel, so the check reads the canvas's own rules: the creator
            # deletes, as in the canvas API, and a sandbox token never does.
            user_id = getattr(context.user, "id", None)
            if is_sandbox_oauth_request(context.request) or not visibility.canvas_deletable_by(
                team_id=canvas.team_id, canvas_id=canvas.id, user_id=user_id
            ):
                raise PermissionDenied("Only the person who created a canvas can delete it.")

        def _authorize_restore(context: RestoreContext, canvas: Canvas) -> None:
            from posthog.api.file_system.file_system import UNDO_DELETE_REFUSED  # noqa: PLC0415
            from posthog.oauth_provenance import is_sandbox_oauth_request  # noqa: PLC0415

            from products.canvas.backend.logic import visibility  # noqa: PLC0415

            # The same answer as every other refused undo, so the endpoint cannot tell apart refs that exist.
            user_id = getattr(context.user, "id", None)
            if is_sandbox_oauth_request(context.request) or not visibility.canvas_restorable_by(
                team_id=canvas.team_id, canvas_id=canvas.id, user_id=user_id
            ):
                raise ValidationError({"detail": UNDO_DELETE_REFUSED})

        register_file_system_visibility_filter("canvas", _filter_rows)
        register_pre_delete_hook("canvas", _authorize_delete)
        register_pre_restore_hook("canvas", _authorize_restore)
