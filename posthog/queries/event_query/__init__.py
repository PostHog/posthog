from django.conf import settings

if settings.EE_AVAILABLE:
    from ee.clickhouse.queries.event_query import EnterpriseEventQuery as EventQuery
else:
    from posthog.queries.event_query.event_query import EventQuery  # type: ignore # noqa: F401
