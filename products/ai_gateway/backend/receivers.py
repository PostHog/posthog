"""Revokes a user's developer mode tokens when they lose eligibility.

Eligibility is checked only at mint, and a token can outlive it by days, so deactivation or losing
staff revokes the user's live tokens through the gateway.
"""

from typing import Any

from django.db import transaction
from django.db.models.signals import pre_save

from posthog.models.user import User


def _revoke_on_lost_eligibility(sender: type[User], instance: User, **kwargs: Any) -> None:
    if instance._state.adding or (instance.is_active and instance.is_staff):
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"is_active", "is_staff"} & set(update_fields):
        return
    from .logic import STAFF_EMAIL_DOMAIN  # noqa: PLC0415 — keeps logic's imports off Django setup

    # Only staff-domain accounts can hold tokens, which keeps the extra read off customer saves. An email
    # moved off the domain is not caught here; offboarding deactivates the account instead.
    if not (instance.email or "").lower().endswith(STAFF_EMAIL_DOMAIN):
        return
    was = sender.objects.filter(pk=instance.pk).values_list("is_active", "is_staff").first()
    if was is None:
        return
    was_active, was_staff = was
    if (was_active and not instance.is_active) or (was_staff and not instance.is_staff):
        from .tasks.tasks import revoke_dev_tokens_for_ineligible_owner  # noqa: PLC0415 — keeps Celery off setup

        user_id = instance.pk
        transaction.on_commit(lambda: revoke_dev_tokens_for_ineligible_owner.delay(user_id))


def connect() -> None:
    pre_save.connect(_revoke_on_lost_eligibility, sender=User, dispatch_uid="ai_gateway_revoke_on_lost_eligibility")
