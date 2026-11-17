"""Revokes a user's developer mode tokens when they lose eligibility or are deleted.

Eligibility is checked only at mint, and a token can outlive it by days, so deactivation, losing
staff, or deletion revokes the user's live tokens through the gateway. A periodic sweep catches
what these hooks miss.
"""

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save, pre_delete, pre_save

import structlog

from posthog.models.user import User

logger = structlog.get_logger(__name__)

_LOST_ELIGIBILITY = "_ai_gateway_lost_eligibility"


def _note_lost_eligibility(sender: type[User], instance: User, **kwargs: Any) -> None:
    if instance._state.adding or (instance.is_active and instance.is_staff):
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"is_active", "is_staff"} & set(update_fields):
        return
    from .logic import STAFF_EMAIL_DOMAIN  # noqa: PLC0415 — keeps logic's imports off Django setup

    # Only staff-domain accounts can hold tokens, which keeps the extra read off customer saves. The
    # sweep catches an owner whose email moved off the domain.
    if not (instance.email or "").lower().endswith(STAFF_EMAIL_DOMAIN):
        return
    was = sender.objects.filter(pk=instance.pk).values_list("is_active", "is_staff").first()
    if was is not None and ((was[0] and not instance.is_active) or (was[1] and not instance.is_staff)):
        setattr(instance, _LOST_ELIGIBILITY, True)


def _revoke_after_save(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    # Queued only once the update is written, so the task reads the new state even in autocommit.
    if not instance.__dict__.pop(_LOST_ELIGIBILITY, False):
        return
    from .tasks.tasks import revoke_dev_tokens_for_ineligible_owner  # noqa: PLC0415 — keeps Celery off setup

    user_id = instance.pk
    # robust: a broker outage must not fail the deactivation; the sweep revokes later.
    transaction.on_commit(lambda: revoke_dev_tokens_for_ineligible_owner.delay(user_id), robust=True)


def _revoke_before_delete(sender: type[User], instance: User, **kwargs: Any) -> None:
    # The token rows are deleted with the user, so the hashes are collected now. A failure here must
    # not abort the delete.
    from .logic import live_token_hashes  # noqa: PLC0415 — keeps logic's imports off Django setup

    try:
        token_hashes = live_token_hashes(instance.pk)
    except Exception:
        logger.exception("ai_gateway_dev_delete_hashes_failed", user_id=instance.pk)
        return
    if not token_hashes:
        return
    from .tasks.tasks import revoke_dev_token_hashes  # noqa: PLC0415 — keeps Celery off setup

    transaction.on_commit(lambda: revoke_dev_token_hashes.delay(token_hashes), robust=True)


def connect() -> None:
    pre_save.connect(_note_lost_eligibility, sender=User, dispatch_uid="ai_gateway_note_lost_eligibility")
    post_save.connect(_revoke_after_save, sender=User, dispatch_uid="ai_gateway_revoke_after_save")
    pre_delete.connect(_revoke_before_delete, sender=User, dispatch_uid="ai_gateway_revoke_before_delete")
