import logging
from collections.abc import Iterator
from contextlib import contextmanager

from django.db import transaction

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ChangeRequest
from products.approvals.backend.notifications import send_approval_requested_notification

logger = logging.getLogger(__name__)


def restore_rolled_back_change_request(change_request: ChangeRequest) -> None:
    """Re-insert a pending ChangeRequest that the caller's transaction rolled back.

    The gate writes the row and then raises, so an exception leaving an atomic block takes
    the row with it while the exception still carries the object. Re-inserting keeps the id
    the caller has already handed to its user.

    The duplicate branch of the gate raises with a change request an earlier request
    committed, so a row that is still there is left alone.
    """
    if ChangeRequest.objects.filter(pk=change_request.pk).exists():
        return

    change_request.save(force_insert=True)
    # The gate queues this notification with `transaction.on_commit`, and Django drops those
    # callbacks when the transaction rolls back. Send it here instead.
    send_approval_requested_notification(change_request)


@contextmanager
def gated_atomic() -> Iterator[None]:
    """``transaction.atomic()`` for a block that can make a gated write.

    A gate raising inside an atomic block rolls its own pending ChangeRequest back, which
    leaves the caller reporting an approval that nobody can act on. This restores the row
    once the block has rolled back and the connection is in autocommit again.

    Use it as the outermost block. Nested inside another atomic block, the restore joins
    that transaction and rolls back with it, so it warns rather than claiming success.
    """
    try:
        with transaction.atomic():
            yield
    except ApprovalRequired as e:
        if e.change_request is not None:
            restore_rolled_back_change_request(e.change_request)
            if transaction.get_connection().in_atomic_block:
                logger.warning(
                    "gated_atomic ran inside another atomic block, so the restored change request "
                    "rolls back again if that block does",
                    extra={"change_request_id": str(e.change_request.id)},
                )
        raise
