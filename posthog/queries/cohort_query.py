from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.queries.enterprise_cohort_query import EnterpriseCohortQuery as CohortQuery
else:
    from posthog.queries.foss_cohort_query import FOSSCohortQuery as CohortQuery  # type: ignore
