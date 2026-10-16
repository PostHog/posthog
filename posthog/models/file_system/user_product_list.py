from typing import ClassVar

from django.conf import settings
from django.db import models, transaction
from django.db.models.expressions import F
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver

from posthog.models.file_system.starred_products import star_default_products
from posthog.models.utils import UpdatedMetaFields, UUIDModel, uuid7


class UserProductList(UUIDModel, UpdatedMetaFields):
    """
    A user's custom sidebar products from before starred products replaced them.

    Nothing writes it anymore. It stays until the starred products backfill has moved every user over.
    """

    # django-stubs normally injects the default `objects` manager during mypy's semantic pass,
    # but this module sits in an import cycle (it imports `user_access_control`/`organization`,
    # which loop back through `posthog.models`). When the plugin analyzes the model mid-cycle it
    # skips the injection, so every `UserProductList.objects` use trips `attr-defined`. Declaring
    # the manager explicitly is order-independent and keeps the type stable regardless of the cycle.
    objects: ClassVar[models.Manager["UserProductList"]]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    product_path = models.CharField(max_length=200)

    # Not using `CreatedMetaFields` because of the clashing `user` reference with `created_by`
    created_at = models.DateTimeField(auto_now_add=True)

    # There's a difference between the `UserProductList` not existing and it being disabled
    # If it's not existing it just means the user hasn't decided whether they want that in
    # the sidebar or not. In that case, we're free to add it to the sidebar as a suggestion
    # when we detect they have been using a product.
    #
    # If the model does exist but this is set to false, we then know that we should not turn
    # it on as a suggestion since it was an intentional change.
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = (("team", "user", "product_path"),)
        indexes = [
            models.Index(F("team_id"), F("user_id"), name="posthog_upl_team_user"),
        ]
        verbose_name = "User Product List"
        verbose_name_plural = "User Product Lists"


@receiver(post_save, sender="ee.AccessControl")
def access_control_created(sender, instance, created, **kwargs):
    """Star the default products for a user who is granted access to a project."""
    if created and instance.organization_member and instance.resource == "project":
        user = instance.organization_member.user
        team = instance.team

        if settings.TEST:
            star_default_products(user, team)
        else:
            transaction.on_commit(lambda: star_default_products(user, team))
