"""
One-off Dagster job that moves sidebar custom products (`UserProductList`) to starred products.

For every user who has not finished the starred products setup:
  - In each project with at most `MAX_PRODUCTS_TO_STAR` enabled custom products, star them all.
  - In a project with more, star nothing. A list that long is a catalog, not a choice.
  - Mark the setup as completed, so a re-run skips the user and the setup card no longer shows.

Safe to re-run: users who finished the setup are skipped, and products the user already starred
are not starred twice. Run it manually from the Dagster UI. Set
ops.backfill_starred_products_op.config.dry_run=True to preview.
"""

from collections import defaultdict

from django.db.models.functions import Lower

import dagster

from posthog.dags.common import JobOwners
from posthog.dataclasses import frozen
from posthog.models.file_system.starred_products import (
    mark_starred_products_setup_completed,
    star_products,
    starred_products_setup_completed,
)
from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.team import Team
from posthog.models.user import User
from posthog.products import Products

MAX_PRODUCTS_TO_STAR = 6


@frozen
class StarredProductsBackfillOutcome:
    projects_starred: int
    projects_over_limit: int
    stars_created: int


def backfill_starred_products_for_user(user: User, *, dry_run: bool) -> StarredProductsBackfillOutcome:
    known_paths = set(Products.get_product_paths())
    # Custom products belong to an environment, but the sidebar shows the stars of the whole project.
    # So each project gets one deduplicated list, and the limit applies to that list.
    paths_by_project_id: dict[int, list[str]] = defaultdict(list)
    team_ids_by_project_id: dict[int, set[int]] = defaultdict(set)
    for project_id, team_id, product_path in (
        UserProductList.objects.filter(user=user, enabled=True)
        .order_by("team__project_id", Lower("product_path"))
        .values_list("team__project_id", "team_id", "product_path")
    ):
        team_ids_by_project_id[project_id].add(team_id)
        # A product removed from the catalog can't be starred, so it doesn't count towards the limit.
        if product_path in known_paths and product_path not in paths_by_project_id[project_id]:
            paths_by_project_id[project_id].append(product_path)

    projects_starred = projects_over_limit = stars_created = 0
    for project_id, paths in paths_by_project_id.items():
        if not paths:
            continue
        if len(paths) > MAX_PRODUCTS_TO_STAR:
            projects_over_limit += 1
            continue
        projects_starred += 1
        if not dry_run:
            # The main environment shares its id with the project. Fall back to the oldest one the user has.
            team_ids = team_ids_by_project_id[project_id]
            team_id = project_id if project_id in team_ids else min(team_ids)
            stars_created += star_products(user, Team.objects.only("id", "project_id").get(id=team_id), paths)

    if not dry_run:
        mark_starred_products_setup_completed(user)

    return StarredProductsBackfillOutcome(
        projects_starred=projects_starred, projects_over_limit=projects_over_limit, stars_created=stars_created
    )


@dagster.op(
    out=dagster.DynamicOut(list[int]),
    config_schema={
        "user_ids": dagster.Field(
            dagster.Array(dagster.Int),
            default_value=[],
            is_required=False,
            description="Specific user IDs to process. If empty, processes every user with custom products.",
        ),
        "batch_size": dagster.Field(dagster.Int, default_value=500, is_required=False),
    },
)
def get_custom_products_user_ids_op(context: dagster.OpExecutionContext):
    user_ids: list[int] = context.op_config["user_ids"] or list(
        UserProductList.objects.filter(enabled=True).order_by("user_id").values_list("user_id", flat=True).distinct()
    )
    batch_size: int = context.op_config["batch_size"]
    context.log.info(f"Processing {len(user_ids)} users in batches of {batch_size}")
    for i in range(0, len(user_ids), batch_size):
        yield dagster.DynamicOutput(user_ids[i : i + batch_size], mapping_key=f"batch_{i // batch_size}")


@dagster.op(
    config_schema={
        "dry_run": dagster.Field(
            dagster.Bool,
            default_value=False,
            description="If True, count what would change but don't write anything.",
        ),
    },
)
def backfill_starred_products_op(context: dagster.OpExecutionContext, user_ids: list[int]) -> dict[str, int]:
    dry_run: bool = context.op_config["dry_run"]
    totals = {
        "users_migrated": 0,
        "skipped_already_completed": 0,
        "skipped_errored": 0,
        "projects_starred": 0,
        "projects_over_limit": 0,
        "stars_created": 0,
    }

    # is_active is read by User.from_db, so leaving it out costs a query per user.
    for user in User.objects.filter(id__in=user_ids).only("id", "ui_configuration", "is_active"):
        if starred_products_setup_completed(user):
            totals["skipped_already_completed"] += 1
            continue
        try:
            outcome = backfill_starred_products_for_user(user, dry_run=dry_run)
        except Exception as e:
            context.log.warning(f"user {user.id}: failed to backfill starred products ({e!r}); skipping")
            totals["skipped_errored"] += 1
            continue
        totals["users_migrated"] += 1
        totals["projects_starred"] += outcome.projects_starred
        totals["projects_over_limit"] += outcome.projects_over_limit
        totals["stars_created"] += outcome.stars_created

    context.log.info(f"Batch: dry_run={dry_run}, {totals}")
    context.add_output_metadata(
        {"dry_run": dagster.MetadataValue.bool(dry_run)}
        | {key: dagster.MetadataValue.int(value) for key, value in totals.items()}
    )
    return totals


@dagster.op
def aggregate_starred_products_backfill_op(context: dagster.OpExecutionContext, results: list[dict[str, int]]) -> None:
    totals: dict[str, int] = defaultdict(int)
    for result in results:
        for key, value in result.items():
            totals[key] += value
    context.log.info(f"Job complete: {dict(totals)}")
    context.add_output_metadata({key: dagster.MetadataValue.int(value) for key, value in totals.items()})


@dagster.job(
    description=(
        "Move sidebar custom products to starred products for users who have not finished the starred "
        f"products setup. Projects with more than {MAX_PRODUCTS_TO_STAR} custom products get no stars. "
        "Every migrated user is marked as having finished the setup. "
        "Set ops.backfill_starred_products_op.config.dry_run=True to preview."
    ),
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def backfill_starred_products_job():
    user_ids = get_custom_products_user_ids_op()
    results = user_ids.map(backfill_starred_products_op)
    aggregate_starred_products_backfill_op(results.collect())
