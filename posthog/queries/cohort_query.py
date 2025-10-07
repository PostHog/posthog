from django.conf import settings

if settings.EE_AVAILABLE:
    from ee.clickhouse.queries.enterprise_cohort_query import EnterpriseCohortQuery as CohortQuery
else:
    from posthog.queries.foss_cohort_query import FOSSCohortQuery as CohortQuery  # type: ignore # noqa: F401
