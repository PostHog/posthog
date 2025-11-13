from django.db import models
from django.db.models.expressions import F

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import UpdatedMetaFields, UUIDModel, uuid7


class UserProductList(UUIDModel, UpdatedMetaFields):
    """
    Stores a user's custom list of products they care about.
    Products are identified by their path from the static products list.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product_path = models.CharField(max_length=200)

    # Not using `CreatedMetaFields` because of the clashing `user` reference with `created_by`
    created_at = models.DateTimeField(auto_now_add=True)

    class Reason(models.TextChoices):
        # User used the product enough to warrant it being in the sidebar
        USAGE = "usage", "Usage"

        # We launch a new product and want to foster adoption
        NEW_PRODUCT = "new_product", "New Product"

        # Sales team can go in and automatically add a product to someone's sidebar
        SALES_LED = ("sales_led", "Sales Led")

    # When the system suggests a product to the user, we store the reason why we suggested it in here
    reason: models.CharField = models.CharField(max_length=32, choices=Reason.choices, null=True)

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

    def __str__(self) -> str:
        return f"{self.team_id}:{self.user_id} - {self.product_path} ({"Enabled" if self.enabled else "Disabled"}) - {self.reason}"
