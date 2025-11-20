from datetime import datetime

from django.utils import timezone

import dagster
import pydantic

from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.team import Team
from posthog.models.user import User
from posthog.products import Products

from dags.common import JobOwners


def get_valid_product_paths() -> set[str]:
    """Get all valid product paths from products.json and hardcoded sidebar products"""
    valid_paths = set[str](Products.get_product_paths())
    return valid_paths


class PopulateConfig(dagster.Config):
    """Configuration for UserProductList populate operations"""

    product_paths: list[str] = pydantic.Field(
        default=[],
        description="List of product paths to add to users' product lists",
    )
    reason: str | None = pydantic.Field(
        default=None,
        description="Reason for creating UserProductList entries",
        examples=UserProductList.Reason.values,
    )
    reason_text: str | None = pydantic.Field(
        default=None,
        description="Optional freeform text to be displayed to the user on hover",
    )
    require_existing_product: str | None = pydantic.Field(
        default=None,
        description="Only create entries for users who already have this product enabled in their UserProductList",
    )
    user_created_before: str | None = pydantic.Field(
        default=None,
        description="ISO format date string. Only process users created before this date (e.g., '2024-01-01T00:00:00Z')",
    )

    # TODO: This should be removed after we've finished running the initial populate job
    # since it's a very confusing configuration knob
    only_users_without_products: bool = pydantic.Field(
        default=False,
        description="Only process users who don't have any existing UserProductList entries",
    )


@dagster.op()
def populate_user_product_list(context: dagster.OpExecutionContext, config: PopulateConfig) -> None:
    """
    Populate UserProductList with configurable options:
    - Set a specific reason for created entries
    - Set optional reason_text for display to users
    - Only create for users who have a specific product enabled
    - Filter by user creation date
    - Option to process only users without existing entries
    """
    if not config.product_paths:
        raise dagster.Failure("product_paths cannot be empty")

    # Validate product paths against valid products
    valid_paths = get_valid_product_paths()
    invalid_paths = [path for path in config.product_paths if path not in valid_paths]
    if invalid_paths:
        raise dagster.Failure(f"Invalid product paths: {invalid_paths}. Valid options: {sorted(valid_paths)}")

    # Validate require_existing_product if provided
    if config.require_existing_product is not None and config.require_existing_product not in valid_paths:
        raise dagster.Failure(
            f"Invalid require_existing_product: {config.require_existing_product}. Valid options: {sorted(valid_paths)}"
        )

    # Validate these arguments are mutually exclusive
    if config.require_existing_product is not None and config.only_users_without_products:
        raise dagster.Failure("require_existing_product and only_users_without_products cannot be used together")

    # Validate reason if provided
    if config.reason:
        if config.reason not in UserProductList.Reason.values:
            raise dagster.Failure(f"Invalid reason: {config.reason}. Valid options: {UserProductList.Reason.values}")

    context.log.info(f"Starting populate for {len(config.product_paths)} products: {config.product_paths}")

    # Build user queryset with filters
    users = User.objects.all()

    # Filter by creation date if specified
    if config.user_created_before is not None:
        created_before = datetime.fromisoformat(config.user_created_before.replace("Z", "+00:00"))
        if created_before.tzinfo is None:
            created_before = timezone.make_aware(created_before)
        users = users.filter(date_joined__lt=created_before)
        context.log.info(f"Filtering users created before {created_before}")

    # Filter by existing products requirement
    if config.require_existing_product:
        users_with_product = (
            UserProductList.objects.filter(product_path=config.require_existing_product, enabled=True)
            .values_list("user_id", flat=True)
            .distinct()
        )
        users = users.filter(id__in=users_with_product)
        context.log.info(f"Only processing users with '{config.require_existing_product}' enabled")

    # Filter to only users without any products if specified
    if config.only_users_without_products:
        user_ids_with_products = UserProductList.objects.values_list("user_id", flat=True).distinct()
        users = users.exclude(id__in=user_ids_with_products)
        context.log.info("Only processing users without existing UserProductList entries")

    # Respect user preference for sidebar suggestions
    users = users.exclude(allow_sidebar_suggestions=False)
    context.log.info("Excluding users with allow_sidebar_suggestions=False")

    total_users = users.count()
    context.log.info(f"Processing {total_users} users")

    created_count = 0
    skipped_count = 0

    for user in users.iterator(chunk_size=1000):
        # Get all teams this user has access to through organization membership
        teams = Team.objects.filter(organization__members=user).distinct()

        for team in teams:
            for product_path in config.product_paths:
                _, created = UserProductList.objects.get_or_create(
                    team=team,
                    user=user,
                    product_path=product_path,
                    defaults={"enabled": True, "reason": config.reason, "reason_text": config.reason_text},
                )

                if created:
                    created_count += 1
                else:
                    skipped_count += 1

                if created_count != 0 and created_count % 1000 == 0:
                    context.log.info(
                        f"Progress: {created_count} created, {skipped_count} skipped (processed user {user.id})"
                    )

    context.log.info(f"Populate complete: {created_count} created, {skipped_count} skipped")

    context.add_output_metadata(
        {
            "created": dagster.MetadataValue.int(created_count),
            "skipped": dagster.MetadataValue.int(skipped_count),
            "total_products": dagster.MetadataValue.int(len(config.product_paths)),
            "reason": dagster.MetadataValue.text(config.reason or "None"),
        }
    )


@dagster.job(tags={"owner": JobOwners.TEAM_GROWTH.value})
def populate_user_product_list_job():
    """
    Add products to users' product lists with configurable options.
    - product_paths: List of product paths to add (required)
    - reason: Optional reason from UserProductList.Reason
    - reason_text: Optional freeform text to display to users on hover
    - require_existing_product: Only add for users who have this product enabled
    - user_created_before: Only process users created before this date (ISO format)
    - only_users_without_products: Only process users without existing entries
    """
    populate_user_product_list()
