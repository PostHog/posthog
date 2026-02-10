import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models import F, Q, Sum

from dateutil import parser
from structlog.types import FilteringBoundLogger

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, Team
from posthog.redis import get_async_client
from posthog.settings import EE_AVAILABLE
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async_pool

from products.data_warehouse.backend.models import ExternalDataJob

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSource


def _get_hash_key(team_id: int) -> str:
    return f"posthog:data_warehouse_row_tracking:{team_id}"


@asynccontextmanager
async def _get_redis():
    """Returns an async Redis client for row tracking operations."""
    redis = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for dwh row tracking: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis = get_async_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        await redis.ping()
    except Exception as e:
        capture_exception(e)

    yield redis


async def setup_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        await redis.hset(_get_hash_key(team_id), str(schema_id), 0)
        await redis.expire(_get_hash_key(team_id), 60 * 60 * 24 * 7)  # 7 day expire


async def increment_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        await redis.hincrby(_get_hash_key(team_id), str(schema_id), rows)


async def decrement_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        if not await redis.hexists(_get_hash_key(team_id), str(schema_id)):
            return

        value = await redis.hget(_get_hash_key(team_id), str(schema_id))
        if not value:
            return

        value_int = int(value)
        if value_int - rows < 0:
            await redis.hset(_get_hash_key(team_id), str(schema_id), 0)
        else:
            await redis.hincrby(_get_hash_key(team_id), str(schema_id), -rows)


async def finish_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    async with _get_redis() as redis:
        if not redis:
            return

        await redis.hdel(_get_hash_key(team_id), str(schema_id))


async def get_rows(team_id: int, schema_id: uuid.UUID | str) -> int:
    async with _get_redis() as redis:
        if not redis:
            return 0

        if await redis.hexists(_get_hash_key(team_id), str(schema_id)):
            value = await redis.hget(_get_hash_key(team_id), str(schema_id))
            if value:
                return int(value)

        return 0


async def get_all_rows_for_team(team_id: int) -> int:
    async with _get_redis() as redis:
        if not redis:
            return 0

        pairs = await redis.hgetall(_get_hash_key(team_id))
        return sum(int(v) for v in pairs.values())


# To be removed after 2025-11-06
dwh_pricing_free_period_start = datetime(2025, 10, 29, 0, 0, 0, tzinfo=UTC)
dwh_pricing_free_period_end = datetime(2025, 11, 6, 0, 0, 0, tzinfo=UTC)


async def will_hit_billing_limit(team_id: int, source: "ExternalDataSource", logger: FilteringBoundLogger) -> bool:
    if not EE_AVAILABLE:
        return False

    try:
        from ee.billing.billing_manager import BillingManager

        await logger.adebug("Running will_hit_billing_limit")

        # Handle free period for newly created data sources
        if source.created_at >= datetime.now(UTC) - timedelta(days=7):
            await logger.ainfo(
                f"Skipping billing limits check for newly created data source for 7-days free rows. source.created_at = {source.created_at}"
            )
            return False

        # Handle free period for data synced during free period (to be removed after 2025-11-06)
        if (
            not TEST
            and datetime.now(UTC) >= dwh_pricing_free_period_start
            and datetime.now(UTC) <= dwh_pricing_free_period_end
        ):
            await logger.ainfo(
                f"Skipping billing limits check for data synced during free period from {dwh_pricing_free_period_start} to {dwh_pricing_free_period_end}."
            )
            return False

        @database_sync_to_async_pool
        def _get_billing_data():
            license = get_cached_instance_license()
            billing_manager = BillingManager(license)
            team = Team.objects.get(id=team_id)
            organization: Organization = team.organization
            all_teams_in_org: list[int] = [
                value[0] for value in Team.objects.filter(organization_id=organization.id).values_list("id")
            ]

            billing_res = billing_manager.get_billing(organization)

            rows_synced_in_billing_period_dict = None
            current_billing_cycle_start_dt = None

            current_billing_cycle_start = billing_res.get("billing_period", {}).get("current_period_start")
            if current_billing_cycle_start is not None:
                current_billing_cycle_start_dt = parser.parse(current_billing_cycle_start)

                # Get all completed rows for all teams in org
                rows_synced_in_billing_period_dict = ExternalDataJob.objects.filter(
                    Q(finished_at__gte=F("pipeline__created_at") + timedelta(days=7)),
                    team_id__in=all_teams_in_org,
                    finished_at__gte=current_billing_cycle_start_dt,
                    billable=True,
                    status=ExternalDataJob.Status.COMPLETED,
                ).aggregate(total_rows=Sum("rows_synced"))

            return (
                organization.id,
                all_teams_in_org,
                billing_res,
                current_billing_cycle_start,
                current_billing_cycle_start_dt,
                rows_synced_in_billing_period_dict,
            )

        (
            org_id,
            all_teams_in_org,
            billing_res,
            current_billing_cycle_start,
            current_billing_cycle_start_dt,
            rows_synced_in_billing_period_dict,
        ) = await _get_billing_data()

        await logger.adebug(f"BillingLimits: Organisation_id = {org_id}")
        await logger.adebug(f"BillingLimits: Teams in org: {all_teams_in_org}")

        if current_billing_cycle_start is None:
            await logger.adebug(
                f"BillingLimits: returning early, no current_period_start available. current_billing_cycle_start = {current_billing_cycle_start}"
            )
            return False

        await logger.adebug(f"BillingLimits: current_billing_cycle_start = {current_billing_cycle_start}")

        usage_summary = billing_res["usage_summary"]
        rows_synced_summary = usage_summary.get("rows_synced", None)

        if not rows_synced_summary:
            await logger.adebug(f"BillingLimits: returning early, no rows_synced key in usage_summary. {usage_summary}")
            return False

        rows_synced_limit = rows_synced_summary.get("limit")

        await logger.adebug(f"BillingLimits: rows_synced_limit = {rows_synced_limit}")

        if rows_synced_limit is None or not isinstance(rows_synced_limit, int | float):
            await logger.adebug("BillingLimits: rows_synced_limit is None or not a number, returning False")
            return False

        rows_synced_in_billing_period = rows_synced_in_billing_period_dict.get("total_rows", 0) or 0

        await logger.adebug(f"BillingLimits: rows_synced_in_billing_period = {rows_synced_in_billing_period}")

        # Get all in-progress rows for all teams in org
        rows_per_team = await asyncio.gather(*[get_all_rows_for_team(t_id) for t_id in all_teams_in_org])
        existing_rows_in_progress = sum(rows_per_team)

        expected_rows = rows_synced_in_billing_period + existing_rows_in_progress

        result = expected_rows > rows_synced_limit

        await logger.adebug(
            f"BillingLimits: expected_rows = {expected_rows}. rows_synced_limit = {rows_synced_limit}. Returning {result}"
        )

        return result
    except Exception as e:
        await logger.adebug(f"BillingLimits: Failed with exception {e}")
        capture_exception(e)

        return False
