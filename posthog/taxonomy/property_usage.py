from datetime import UTC, date, datetime, timedelta

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.event_usage import PROPERTY_USAGE_APP_SOURCE, property_usage_instance_id
from posthog.models import PropertyDefinition, Team, User

USAGE_WINDOW_DAYS = 30
TOP_USERS_LIMIT = 10
# Query runs without a user, such as shared dashboards, subscriptions and alerts, log under this id.
ANONYMOUS_APP_SOURCE_ID = "anonymous"


@frozen
class PropertyUsageDay:
    date: date
    count: int


@frozen
class PropertyUsageUser:
    user: User
    count: int
    last_queried_at: datetime


@frozen
class PropertyUsageDetail:
    query_usage_30_day: int
    last_queried_at: datetime | None
    daily: tuple[PropertyUsageDay, ...]
    top_users: tuple[PropertyUsageUser, ...]
    distinct_users: int
    automated_query_usage_30_day: int


def property_definition_usage_instance_id(definition: PropertyDefinition) -> str:
    return property_usage_instance_id(
        PropertyDefinition.Type(definition.type).label, definition.name, definition.group_type_index
    )


def fetch_property_usage_detail(team: Team, definition: PropertyDefinition) -> PropertyUsageDetail:
    today = datetime.now(team.timezone_info).date()
    first_day = today - timedelta(days=USAGE_WINDOW_DAYS - 1)
    window_start = datetime.combine(first_day, datetime.min.time(), tzinfo=team.timezone_info).astimezone(UTC)

    tag_queries(product=Product.PRODUCT_ANALYTICS, feature=Feature.PROPERTY_DEFINITION_SCENE)
    rows = sync_execute(
        """
        SELECT toDate(timestamp, %(timezone)s) AS day, app_source_id, sum(count), max(timestamp)
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = %(app_source)s
          AND metric_name = %(metric_name)s
          AND instance_id = %(instance_id)s
          AND timestamp >= toDateTime64(%(after)s, 6, 'UTC')
        GROUP BY day, app_source_id
        """,
        {
            "team_id": team.pk,
            "timezone": team.timezone,
            "app_source": PROPERTY_USAGE_APP_SOURCE,
            "metric_name": "viewed",
            "instance_id": property_definition_usage_instance_id(definition),
            "after": window_start.strftime("%Y-%m-%d %H:%M:%S"),
        },
        team_id=team.pk,
    )

    counts_by_day: dict[date, int] = {}
    counts_by_user_id: dict[int, int] = {}
    last_queried_by_user_id: dict[int, datetime] = {}
    automated = 0
    last_queried_at: datetime | None = None
    for day, app_source_id, raw_count, max_timestamp in rows or []:
        count = int(raw_count)
        max_timestamp = max_timestamp.replace(tzinfo=UTC) if max_timestamp.tzinfo is None else max_timestamp
        counts_by_day[day] = counts_by_day.get(day, 0) + count
        last_queried_at = max(last_queried_at, max_timestamp) if last_queried_at else max_timestamp
        if app_source_id == ANONYMOUS_APP_SOURCE_ID or not app_source_id.isdigit():
            automated += count
            continue
        user_id = int(app_source_id)
        counts_by_user_id[user_id] = counts_by_user_id.get(user_id, 0) + count
        previous = last_queried_by_user_id.get(user_id)
        last_queried_by_user_id[user_id] = max(previous, max_timestamp) if previous else max_timestamp

    # Only name people who are still in the organization. Former members count toward the totals only.
    top_user_ids = sorted(counts_by_user_id, key=lambda user_id: counts_by_user_id[user_id], reverse=True)
    members = {
        user.id: user
        for user in User.objects.filter(
            id__in=top_user_ids, organization_membership__organization_id=team.organization_id
        )
    }
    top_users = tuple(
        PropertyUsageUser(
            user=members[user_id],
            count=counts_by_user_id[user_id],
            last_queried_at=last_queried_by_user_id[user_id],
        )
        for user_id in top_user_ids
        if user_id in members
    )[:TOP_USERS_LIMIT]

    days = [first_day + timedelta(days=offset) for offset in range(USAGE_WINDOW_DAYS)]
    return PropertyUsageDetail(
        query_usage_30_day=sum(counts_by_day.values()),
        last_queried_at=last_queried_at,
        daily=tuple(PropertyUsageDay(date=day, count=counts_by_day.get(day, 0)) for day in days),
        top_users=top_users,
        distinct_users=len(counts_by_user_id),
        automated_query_usage_30_day=automated,
    )
