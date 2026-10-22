from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models.signals import post_save

from products.account_audits.backend.models import AccountAuditAdmission

if TYPE_CHECKING:
    from posthog.models.file_system.file_system_view_log import FileSystemViewLog


def _list_audit_notebook(view: "FileSystemViewLog") -> None:
    if not AccountAuditAdmission.objects.for_team(view.team_id).filter(notebook_short_id=view.ref).exists():
        return

    from products.notebooks.backend.facade import api as notebooks_api  # noqa: PLC0415 — keeps notebooks off startup

    notebooks_api.make_notebook_listed(view.team_id, view.ref, user=view.user)


def list_viewed_audit_notebook(sender: type, instance: "FileSystemViewLog", created: bool, **kwargs: object) -> None:
    if not created or instance.type != "notebook":
        return
    # The view-log insert runs in its own atomic block, so a failure here must not roll it back.
    transaction.on_commit(lambda: _list_audit_notebook(instance), robust=True)


def connect() -> None:
    post_save.connect(
        list_viewed_audit_notebook,
        sender="posthog.FileSystemViewLog",
        dispatch_uid="account_audits_list_viewed_audit_notebook",
    )
