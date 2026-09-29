from typing import Any

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.user import User

from products.customer_analytics.backend.facade.enums import AccountViewVisibility
from products.customer_analytics.backend.models.account_view import AccountView


@receiver(pre_delete, sender=User)
def delete_private_account_views_for_deleted_user(
    sender: type[User], instance: User, using: str, **kwargs: Any
) -> None:
    AccountView.objects.unscoped().filter(
        created_by_id=instance.id,
        visibility=AccountViewVisibility.PRIVATE,
    ).delete()
