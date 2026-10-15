from django.apps import AppConfig


class CanvasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.canvas.backend"
    label = "canvas"
    verbose_name = "Canvas"

    def ready(self) -> None:
        # Registers the artifact-delivery configuration system checks and the
        # search-index signal receivers.
        from rest_framework.exceptions import PermissionDenied  # noqa: PLC0415

        from posthog.api.file_system.deletion import (  # noqa: PLC0415
            DeletionContext,
            register_file_system_type,
            register_pre_delete_hook,
        )
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        from products.canvas.backend import checks, search_sync  # noqa: F401, PLC0415
        from products.canvas.backend.logic import visibility  # noqa: PLC0415
        from products.canvas.backend.models import Canvas  # noqa: PLC0415

        register_mixin_model("canvas", Canvas)
        register_file_system_type(
            "canvas",
            "canvas",
            "Canvas",
            soft_delete_field="deleted",
            undo_message="Send PATCH /api/projects/@current/canvases/{id} with deleted=false.",
        )

        def _authorize_delete(context: DeletionContext, canvas: Canvas) -> None:
            # The file system row carries no channel, so the delete checks the canvas's own visibility.
            user_id = getattr(context.user, "id", None)
            if not visibility.canvas_is_visible(team_id=canvas.team_id, canvas_id=canvas.id, user_id=user_id):
                raise PermissionDenied("You don't have access to this canvas.")

        register_pre_delete_hook("canvas", _authorize_delete)
