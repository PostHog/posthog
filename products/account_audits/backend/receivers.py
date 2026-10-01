from typing import TYPE_CHECKING

from django.db.models.signals import post_save

from products.account_audits.backend.models import AccountAuditAdmission

if TYPE_CHECKING:
    from posthog.models.file_system.file_system_view_log import FileSystemViewLog


def list_viewed_audit_notebook(sender: type, instance: "FileSystemViewLog", created: bool, **kwargs: object) -> None:
    if not created or instance.type != "notebook":
        return
    if not AccountAuditAdmission.objects.for_team(instance.team_id).filter(notebook_short_id=instance.ref).exists():
        return

    # Deferred: keeps notebook dependencies off Django startup.
    from products.notebooks.backend.facade.api import make_notebook_listed  # noqa: PLC0415

    make_notebook_listed(instance.team_id, instance.ref, user=instance.user)


def connect() -> None:
    post_save.connect(
        list_viewed_audit_notebook,
        sender="posthog.FileSystemViewLog",
        dispatch_uid="account_audits_list_viewed_audit_notebook",
    )
