from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from products.enterprise.backend.clickhouse.queries.event_query import EnterpriseEventQuery as EventQuery
else:
    from posthog.queries.event_query.event_query import EventQuery  # type: ignore # noqa: F401
