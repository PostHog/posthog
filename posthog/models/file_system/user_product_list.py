import random
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.db import models, transaction
from django.db.models import Count
from django.db.models.expressions import F
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver

from posthog.schema import ProductIntentContext, ProductKey

from posthog.models.utils import UpdatedMetaFields, UUIDModel, uuid7
from posthog.products import Products

if TYPE_CHECKING:
    from posthog.models.product_intent.product_intent import ProductIntent
    from posthog.models.team import Team
    from posthog.models.user import User


def get_user_product_list_count(team: "Team") -> list[dict[str, Any]]:
    """
    Get product counts for all items in a team, ranked by popularity.
    Returns a list of dicts with 'product_path' and 'colleague_count' keys, ordered by count descending.
    """
    return list[dict[str, Any]](
        UserProductList.objects.filter(team=team, enabled=True)
        .values("product_path")
        .annotate(colleague_count=Count("user", distinct=True))
        .order_by("-colleague_count")
    )


def backfill_user_product_list_for_new_user(user: "User", team: "Team") -> None:
    """
    Backfill UserProductList entries for a new user in a new team based on what
    they have enabled in other teams they belong to.
    """
    UserProductList.backfill_from_other_teams(user, team)
    UserProductList.sync_from_team_colleagues(user, team, count=3)


class UserProductList(UUIDModel, UpdatedMetaFields):
    """
    Stores a user's custom list of products they care about.
    Products are identified by their path from the static products list.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    product_path = models.CharField(max_length=200)

    # Not using `CreatedMetaFields` because of the clashing `user` reference with `created_by`
    created_at = models.DateTimeField(auto_now_add=True)

    class Reason(models.TextChoices):
        # User chose this product during onboarding
        ONBOARDING = "onboarding", "Onboarding"

        # User showed intent for the product
        PRODUCT_INTENT = "product_intent", "Product Intent"

        # Colleagues on the same team have the product in their sidebar
        USED_BY_COLLEAGUES = "used_by_colleagues", "Used by Colleagues"

        # User has a similar product in their sidebar
        USED_SIMILAR_PRODUCTS = "used_similar_products", "Used Similar Products"

        # User has this product on another team they belong to
        USED_ON_SEPARATE_TEAM = "used_on_separate_team", "Used on Separate Team"

        # We launch a new product and want to foster adoption
        NEW_PRODUCT = "new_product", "New Product"

        # Sales team can go in and automatically add a product to someone's sidebar
        SALES_LED = "sales_led", "Sales Led"

    # When the system suggests a product to the user, we store the reason why we suggested it in here
    # And and optional freeform text field to be displayed to the user on hover
    reason: models.CharField = models.CharField(max_length=32, choices=Reason.choices, null=True)
    reason_text: models.TextField = models.TextField(null=True)

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

    @staticmethod
    def create_from_product_intent(product_intent: "ProductIntent", user: "User") -> "list[UserProductList]":
        if user.allow_sidebar_suggestions is False:
            return []

        products = Products.get_products_by_intent(cast(ProductKey, product_intent.product_type))
        if not products:
            return []

        onboarding_contexts = [
            ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY,
            ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___SECONDARY,
            ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
        ]
        has_onboarding_context = any(context in (product_intent.contexts or {}) for context in onboarding_contexts)
        reason = UserProductList.Reason.ONBOARDING if has_onboarding_context else UserProductList.Reason.PRODUCT_INTENT

        user_product_lists = []
        for product in products:
            item, _ = UserProductList.objects.get_or_create(
                user=user,
                team=product_intent.team,
                product_path=product.path,
                defaults={
                    "enabled": True,
                    "reason": reason,
                },
            )
            user_product_lists.append(item)

        return user_product_lists

    @staticmethod
    def sync_from_team_colleagues(
        user: "User",
        team: "Team",
        count: int = 1,
        colleague_product_counts: list[dict[str, Any]] | None = None,
    ) -> "list[UserProductList]":
        """
        Create UserProductList entries for a user based on what their team colleagues have.
        Products are ranked by how many colleagues have them enabled, and only the top `count`
        items that the user doesn't already have enabled are included.

        Args:
            user: The user to sync products for
            team: The team to check colleagues in
            count: Maximum number of products to suggest
            colleague_product_counts: Optional precomputed colleague product counts.
                If not provided, will be computed automatically.
        """
        if user.allow_sidebar_suggestions is False:
            return []

        # Get products the user already has (enabled or disabled - we'll exclude these)
        user_existing_products = set(
            UserProductList.objects.filter(user=user, team=team).values_list("product_path", flat=True)
        )

        # Count how many colleagues have each product_path enabled
        if colleague_product_counts is None:
            colleague_product_counts = get_user_product_list_count(team)

        # Filter out products user already has and take top `count` items
        top_products = [
            item["product_path"]
            for item in colleague_product_counts
            if item["product_path"] not in user_existing_products
        ][:count]

        # Create UserProductList entries for the top products
        created_items = []
        for product_path in top_products:
            item, created = UserProductList.objects.get_or_create(
                user=user,
                team=team,
                product_path=product_path,
                defaults={
                    "enabled": True,
                    "reason": UserProductList.Reason.USED_BY_COLLEAGUES,
                },
            )

            if created:
                created_items.append(item)

        return created_items

    @staticmethod
    def backfill_from_other_teams(user: "User", team: "Team") -> "list[UserProductList]":
        """
        Backfill UserProductList entries for a user in a new team based on what
        they have enabled in other teams they belong to.
        """
        from posthog.models.team import Team

        # We IGNORE the user's suggestion config because we want them to have
        # at least some products in their sidebar to start with when backfilling from
        # their own teams.
        #
        # if user.allow_sidebar_suggestions is False:
        #     return []

        # Get all other teams the user belongs to (through organization membership)
        user_organizations = user.organization_memberships.values_list("organization_id", flat=True)
        other_teams = Team.objects.filter(organization_id__in=user_organizations).exclude(id=team.id)

        # Get all product paths the user has enabled in other teams
        user_product_paths = set(
            UserProductList.objects.filter(user=user, team__in=other_teams, enabled=True).values_list(
                "product_path", flat=True
            )
        )

        # Create UserProductList entries for the missing products
        created_items = []
        for product_path in user_product_paths:
            item, created = UserProductList.objects.get_or_create(
                user=user,
                team=team,
                product_path=product_path,
                defaults={
                    "enabled": True,
                    "reason": UserProductList.Reason.USED_ON_SEPARATE_TEAM,
                },
            )

            if created:
                created_items.append(item)

        return created_items

    @staticmethod
    def sync_cross_sell_products(
        user: "User",
        team: "Team",
        max_products: int = 1,
        ignored_categories: list[str] | None = None,
    ) -> "list[UserProductList]":
        """
        Sync cross-sell products for a user based on products they already have enabled.
        For each enabled product, finds other products from the same category.
        Randomly selects up to max_products from all cross-sell candidates across all categories.

        Args:
            user: The user to sync products for
            team: The team to sync products in
            max_products: Maximum number of cross-sell products to suggest (across all categories)
            ignored_categories: List of category names to ignore when suggesting cross-sell products.
                               Defaults to ["Tools", "Unreleased"]

        Returns:
            List of newly created UserProductList entries
        """
        if user.allow_sidebar_suggestions is False:
            return []

        # By default we don't want to add new items from the Tools and Unreleased categories since:
        # - Tools aren't relevant to cross-sell
        # - Unreleased products are not yet ready for cross-sell and aren't correlated one to another
        if ignored_categories is None:
            ignored_categories = ["Tools", "Unreleased"]

        ignored_categories_set = set(ignored_categories)

        user_enabled_products = UserProductList.objects.filter(user=user, team=team, enabled=True).values_list(
            "product_path", flat=True
        )

        user_existing_products = set(
            UserProductList.objects.filter(user=user, team=team).values_list("product_path", flat=True)
        )

        products_by_category = Products.get_products_by_category()
        product_to_category: dict[str, str] = {}
        for product in Products.products():
            if product.category:
                product_to_category[product.path] = product.category

        all_cross_sell_candidates: set[str] = set()
        for product_path in user_enabled_products:
            category = product_to_category.get(product_path)
            if not category or category in ignored_categories_set:
                continue

            category_products = set(products_by_category.get(category, []))
            cross_sell_options = category_products - user_existing_products - {product_path}

            filtered_options = {
                opt for opt in cross_sell_options if product_to_category.get(opt) not in ignored_categories_set
            }
            all_cross_sell_candidates.update(filtered_options)

        if not all_cross_sell_candidates:
            return []

        candidates_list = list(all_cross_sell_candidates)
        random.shuffle(candidates_list)
        selected = candidates_list[:max_products]

        created_items = []
        for product_path in selected:
            item, created = UserProductList.objects.get_or_create(
                user=user,
                team=team,
                product_path=product_path,
                defaults={
                    "enabled": True,
                    "reason": UserProductList.Reason.USED_SIMILAR_PRODUCTS,
                },
            )

            if created:
                created_items.append(item)

        return created_items


@receiver(post_save, sender="ee.AccessControl")
def access_control_created(sender, instance, created, **kwargs):
    """
    Handle AccessControl creation to backfill UserProductList for users gaining access to a team.

    When a user is granted access to a team via AccessControl, we backfill their UserProductList
    based on what they have enabled in other teams they belong to.
    """
    if created and instance.organization_member and instance.resource == "project":
        user = instance.organization_member.user
        team = instance.team

        if settings.TEST:
            backfill_user_product_list_for_new_user(user, team)
        else:
            transaction.on_commit(lambda: backfill_user_product_list_for_new_user(user, team))
