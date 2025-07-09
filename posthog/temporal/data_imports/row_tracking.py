from contextlib import contextmanager
from dateutil import parser
from django.conf import settings
from django.db.models import Sum
import uuid
from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, Team
from posthog.settings import EE_AVAILABLE
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.warehouse.models import ExternalDataJob
from posthog.redis import get_client


def _get_hash_key(team_id: int) -> str:
    return f"posthog:data_warehouse_row_tracking:{team_id}"


@contextmanager
def _get_redis():
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for dwh row tracking: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        # Ensure redis is up and alive
        redis = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        redis.ping()

        yield redis
    except Exception as e:
        capture_exception(e)
        yield None


def setup_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        redis.hset(_get_hash_key(team_id), str(schema_id), 0)
        redis.expire(_get_hash_key(team_id), 60 * 60 * 24 * 7)  # 7 day expire


def increment_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        redis.hincrby(_get_hash_key(team_id), str(schema_id), rows)


def decrement_rows(team_id: int, schema_id: uuid.UUID | str, rows: int) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        if not redis.hexists(_get_hash_key(team_id), str(schema_id)):
            return

        value = redis.hget(_get_hash_key(team_id), str(schema_id))
        if not value:
            return

        value_int = int(value)
        if value_int - rows < 0:
            redis.hset(_get_hash_key(team_id), str(schema_id), 0)
        else:
            redis.hincrby(_get_hash_key(team_id), str(schema_id), -rows)


def finish_row_tracking(team_id: int, schema_id: uuid.UUID | str) -> None:
    with _get_redis() as redis:
        if not redis:
            return

        redis.hdel(_get_hash_key(team_id), str(schema_id))


def get_rows(team_id: int, schema_id: uuid.UUID | str) -> int:
    with _get_redis() as redis:
        if not redis:
            return 0

        if redis.hexists(_get_hash_key(team_id), str(schema_id)):
            value = redis.hget(_get_hash_key(team_id), str(schema_id))
            if value:
                return int(value)

        return 0


def get_all_rows_for_team(team_id: int) -> int:
    with _get_redis() as redis:
        if not redis:
            return 0

        pairs = redis.hgetall(_get_hash_key(team_id))
        return sum(int(v) for v in pairs.values())


def will_hit_billing_limit(team_id: int, logger: FilteringBoundLogger) -> bool:
    if not EE_AVAILABLE:
        return False

    try:
        from ee.billing.billing_manager import BillingManager

        logger.debug("Running will_hit_billing_limit")

        license = get_cached_instance_license()
        billing_manager = BillingManager(license)
        team = Team.objects.get(id=team_id)
        organization: Organization = team.organization
        all_teams_in_org: list[int] = [
            value[0] for value in Team.objects.filter(organization_id=organization.id).values_list("id")
        ]

        logger.debug(f"will_hit_billing_limit: Organisation_id = {organization.id}")
        logger.debug(f"will_hit_billing_limit: Teams in org: {all_teams_in_org}")

        billing_res = billing_manager.get_billing(organization)

        logger.debug(f"will_hit_billing_limit: billing_res = {billing_res}")

        current_billing_cycle_start = billing_res.get("billing_period", {}).get("current_period_start")
        if current_billing_cycle_start is None:
            logger.debug(
                f"will_hit_billing_limit: returning early, no current_period_start available. current_billing_cycle_start = {current_billing_cycle_start}"
            )
            return False

        current_billing_cycle_start_dt = parser.parse(current_billing_cycle_start)

        logger.debug(f"will_hit_billing_limit: current_billing_cycle_start = {current_billing_cycle_start}")

        usage_summary = billing_res["usage_summary"]
        rows_synced_summary = usage_summary.get("rows_synced", None)

        if not rows_synced_summary:
            logger.debug(
                f"will_hit_billing_limit: returning early, no rows_synced key in usage_summary. {usage_summary}"
            )
            return False

        rows_synced_limit = rows_synced_summary.get("limit")

        logger.debug(f"will_hit_billing_limit: rows_synced_limit = {rows_synced_limit}")

        if rows_synced_limit is None or not isinstance(rows_synced_limit, int | float):
            logger.debug("will_hit_billing_limit: rows_synced_limit is None or not a number, returning False")
            return False

        # Get all completed rows for all teams in org
        rows_synced_in_billing_period_dict = ExternalDataJob.objects.filter(
            team_id__in=all_teams_in_org,
            finished_at__gte=current_billing_cycle_start_dt,
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        ).aggregate(total_rows=Sum("rows_synced"))

        rows_synced_in_billing_period = rows_synced_in_billing_period_dict.get("total_rows", 0) or 0

        logger.debug(f"will_hit_billing_limit: rows_synced_in_billing_period = {rows_synced_in_billing_period}")

        # Get all in-progress rows for all teams in org
        existing_rows_in_progress = sum(get_all_rows_for_team(t_id) for t_id in all_teams_in_org)

        expected_rows = rows_synced_in_billing_period + existing_rows_in_progress

        result = expected_rows > rows_synced_limit

        logger.debug(
            f"will_hit_billing_limit: expected_rows = {expected_rows}. rows_synced_limit = {rows_synced_limit}. Returning {result}"
        )

        return result
    except Exception as e:
        logger.debug(f"will_hit_billing_limit: Failed with exception {e}")
        capture_exception(e)

        return False
