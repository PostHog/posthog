from django.db import models


class PendingOrganizationReconcile(models.Model):
    """An organization whose plan changed and whose schedules have not been reconciled since.

    Written in the transaction that stores the plan, so a task lost on the way to the broker leaves a
    row for `retry_pending_organization_reconciles` to pick up. The plan change does not fire again.
    The id is not a foreign key, because a row outliving its organization only costs one empty reconcile.
    """

    organization_id = models.UUIDField(primary_key=True)
    requested_at = models.DateTimeField()
    first_requested_at = models.DateTimeField()
