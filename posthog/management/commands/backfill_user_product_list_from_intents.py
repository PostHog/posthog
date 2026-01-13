from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import structlog

from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.team import Team
from posthog.products import Products
from posthog.schema import ProductKey

logger = structlog.get_logger(__name__)


def backfill_user_product_list_from_intents(
    dry_run: bool = True,
    limit: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict[str, int]:
    """
    Backfill UserProductList entries for users created in a date range based on their product intents.

    Processes per team (project):
    1. For each team, gets users with access who were created in the date range
    2. Checks if user has more than 5 existing UserProductList entries for that team
    3. Respects user's allow_sidebar_suggestions setting
    4. Deletes all UserProductList entries without a reason (organically set) for that user/team
    5. Finds all product intents for that team
    6. Creates UserProductList entries using UserProductList.create_from_product_intent()

    Args:
        dry_run: If True, don't make any changes, just log what would be done
        limit: Optional limit on number of teams to process
        start_date: Start date for filtering users (defaults to 2025-01-01)
        end_date: End date for filtering users (defaults to 2026-01-01)

    Returns:
        Dictionary with statistics: {
            'teams_processed': number of teams processed,
            'users_processed': number of users processed,
            'users_skipped': number of users skipped,
            'errors': number of errors,
            'created': number of UserProductList entries created,
            'deleted': number of entries deleted
        }
    """
    # Default to 2024-Jan 2026 if dates not provided
    if start_date is None:
        start_date = datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC"))
    if end_date is None:
        end_date = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
    # Get all teams
    teams = Team.objects.exclude(id=0).order_by("id")
    if limit:
        teams = teams[:limit]
    total_teams = teams.count()
    logger.info(
        f"Processing teams for users created between {start_date.date()} and {end_date.date()}. "
        f"Total teams: {total_teams}"
    )
    teams_processed = 0
    users_processed = 0
    users_skipped = 0
    error_count = 0
    total_product_lists_created = 0
    total_entries_deleted = 0
    for team in teams.iterator(chunk_size=100):
        try:
            # Get all users with access to this team who were created in the date range
            team_users = (
                team.all_users_with_access()
                .filter(date_joined__gte=start_date, date_joined__lt=end_date)
                .order_by("date_joined")
            )
            if not team_users.exists():
                continue
            team_users_processed = 0
            team_users_skipped = 0
            team_entries_created = 0
            team_entries_deleted = 0
            for user in team_users.iterator(chunk_size=10):
                try:
                    # Respect user's allow_sidebar_suggestions setting
                    if user.allow_sidebar_suggestions is False:
                        logger.debug(
                            f"Team {team.id}, User {user.id} ({user.email}): allow_sidebar_suggestions=False, skipping"
                        )
                        team_users_skipped += 1
                        continue
                    # Check if user has more than 5 existing UserProductList entries for this team
                    existing_count = UserProductList.objects.filter(
                        user=user, team=team
                    ).count()
                    if existing_count <= 5:
                        logger.debug(
                            f"Team {team.id}, User {user.id} ({user.email}): has {existing_count} existing entries (<=5) for this team, skipping"
                        )
                        team_users_skipped += 1
                        continue
                    # Delete all entries without a reason (organically set) for this user/team
                    entries_without_reason = UserProductList.objects.filter(
                        user=user, team=team, reason__isnull=True
                    )
                    entries_to_delete_count = entries_without_reason.count()
                    if entries_to_delete_count > 0:
                        if not dry_run:
                            deleted_count = entries_without_reason.delete()[0]
                            logger.info(
                                f"Team {team.id}, User {user.id} ({user.email}): Deleted {deleted_count} UserProductList entries without reason"
                            )
                            team_entries_deleted += deleted_count
                        else:
                            logger.info(
                                f"Team {team.id}, User {user.id} ({user.email}): Would delete {entries_to_delete_count} UserProductList entries without reason"
                            )
                            team_entries_deleted += entries_to_delete_count
                    # Get all product intents for this team
                    product_intents = ProductIntent.objects.filter(team=team)
                    if not product_intents.exists():
                        logger.debug(
                            f"Team {team.id}, User {user.id} ({user.email}): Team has no product intents, skipping"
                        )
                        team_users_skipped += 1
                        continue
                    # Create UserProductList entries for each product intent
                    user_product_lists_created = 0
                    for product_intent in product_intents:
                        try:
                            if not dry_run:
                                created_lists = (
                                    UserProductList.create_from_product_intent(
                                        product_intent, user
                                    )
                                )
                                user_product_lists_created += len(created_lists)
                            else:
                                # In dry-run mode, just check what would be created
                                products = Products.get_products_by_intent(
                                    ProductKey(product_intent.product_type)
                                )
                                user_product_lists_created += (
                                    len(products) if products else 0
                                )
                        except Exception as e:
                            logger.warning(
                                f"Team {team.id}, User {user.id}, product_intent {product_intent.id}: Failed to create UserProductList: {e}"
                            )
                            error_count += 1
                    if user_product_lists_created > 0 or entries_to_delete_count > 0:
                        logger.info(
                            f"Team {team.id}, User {user.id} ({user.email}): Created {user_product_lists_created} UserProductList entries "
                            f"from {product_intents.count()} product intents"
                        )
                        team_entries_created += user_product_lists_created
                    team_users_processed += 1
                except Exception as e:
                    logger.exception(
                        f"Team {team.id}, User {user.id} ({user.email}): Error processing user: {e}"
                    )
                    error_count += 1
            if team_users_processed > 0 or team_entries_deleted > 0:
                logger.info(
                    f"Team {team.id}: Processed {team_users_processed} users, skipped {team_users_skipped}, "
                    f"created {team_entries_created} entries, deleted {team_entries_deleted} entries"
                )
            teams_processed += 1
            users_processed += team_users_processed
            users_skipped += team_users_skipped
            total_product_lists_created += team_entries_created
            total_entries_deleted += team_entries_deleted
            if teams_processed % 100 == 0:
                logger.info(
                    f"Progress: {teams_processed}/{total_teams} teams processed, "
                    f"{users_processed} users processed, {users_skipped} users skipped"
                )
        except Exception as e:
            logger.exception(f"Team {team.id}: Error processing team: {e}")
            error_count += 1
    logger.info(
        f"Completed: {teams_processed} teams processed, {users_processed} users processed, "
        f"{users_skipped} users skipped, {error_count} errors, "
        f"{total_product_lists_created} UserProductList entries created, {total_entries_deleted} entries deleted"
    )
    if dry_run:
        logger.info("DRY RUN - No changes were made")
    return {
        "teams_processed": teams_processed,
        "users_processed": users_processed,
        "users_skipped": users_skipped,
        "errors": error_count,
        "created": total_product_lists_created,
        "deleted": total_entries_deleted,
    }
