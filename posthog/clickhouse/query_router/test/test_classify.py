from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_router.classify import classify_query, pool_for
from posthog.clickhouse.query_router.config import Pool, QueryClass
from posthog.clickhouse.query_tagging import AccessMethod, Feature, Product, QueryTags
from posthog.clickhouse.workload import Workload

PROCESS_QUERY_TASK_ID = "posthog.tasks.tasks.process_query_task"

EXEMPT_USERS = (
    ClickHouseUser.MIGRATIONS,
    ClickHouseUser.OPS,
    ClickHouseUser.BACKUPS,
    ClickHouseUser.PART_BREAKER,
    ClickHouseUser.DELETION_EXECUTOR,
    ClickHouseUser.DICT_READER,
    ClickHouseUser.BATCH_EXPORT,
    ClickHouseUser.BILLING,
)


class TestClassify(SimpleTestCase):
    @parameterized.expand(
        [
            *[(f"exempt_user_{user.value}", QueryTags(kind="request"), user, None) for user in EXEMPT_USERS],
            (
                "query_task_for_a_person_in_the_app",
                QueryTags(kind="celery", id=PROCESS_QUERY_TASK_ID),
                ClickHouseUser.APP,
                QueryClass.INTERACTIVE,
            ),
            (
                "query_task_for_an_api_key_caller",
                QueryTags(kind="celery", id=PROCESS_QUERY_TASK_ID, access_method=AccessMethod.PERSONAL_API_KEY),
                ClickHouseUser.API,
                QueryClass.API,
            ),
            (
                "query_task_enqueued_by_a_background_job",
                QueryTags(kind="celery", id=PROCESS_QUERY_TASK_ID, query_router_class="background"),
                ClickHouseUser.APP,
                QueryClass.BACKGROUND,
            ),
            (
                "query_task_enqueued_by_an_ai_worker",
                QueryTags(kind="celery", id=PROCESS_QUERY_TASK_ID, product=Product.MAX_AI, query_router_class="async"),
                ClickHouseUser.MAX_AI,
                QueryClass.ASYNC,
            ),
            (
                "query_task_enqueued_before_the_class_was_stored",
                QueryTags(kind="celery", id=PROCESS_QUERY_TASK_ID, feature=Feature.POSTHOG_AI),
                ClickHouseUser.APP,
                QueryClass.INTERACTIVE,
            ),
            ("alert", QueryTags(kind="celery", feature=Feature.ALERTING), ClickHouseUser.DEFAULT, QueryClass.ASYNC),
            (
                "max_ai_product",
                QueryTags(kind="temporal", product=Product.MAX_AI),
                ClickHouseUser.MAX_AI,
                QueryClass.ASYNC,
            ),
            (
                "posthog_ai_feature",
                QueryTags(kind="celery", feature=Feature.POSTHOG_AI),
                ClickHouseUser.DEFAULT,
                QueryClass.ASYNC,
            ),
            ("mcp_feature", QueryTags(kind="temporal", feature=Feature.MCP), ClickHouseUser.DEFAULT, QueryClass.ASYNC),
            (
                "max_ai_request_by_a_person",
                QueryTags(kind="request", product=Product.MAX_AI),
                ClickHouseUser.MAX_AI,
                QueryClass.INTERACTIVE,
            ),
            (
                "mcp_request_with_api_key",
                QueryTags(kind="request", feature=Feature.MCP, access_method=AccessMethod.PERSONAL_API_KEY),
                ClickHouseUser.API,
                QueryClass.API,
            ),
            ("ui_request", QueryTags(kind="request"), ClickHouseUser.APP, QueryClass.INTERACTIVE),
            (
                "oauth_request",
                QueryTags(kind="request", access_method=AccessMethod.OAUTH),
                ClickHouseUser.APP,
                QueryClass.INTERACTIVE,
            ),
            (
                "personal_api_key_request",
                QueryTags(kind="request", access_method=AccessMethod.PERSONAL_API_KEY),
                ClickHouseUser.API,
                QueryClass.API,
            ),
            (
                "project_secret_api_key_request",
                QueryTags(kind="request", access_method=AccessMethod.PROJECT_SECRET_API_KEY),
                ClickHouseUser.API,
                QueryClass.API,
            ),
            ("cohort_calculation", QueryTags(kind="celery"), ClickHouseUser.COHORTS, QueryClass.BACKGROUND),
            ("temporal", QueryTags(kind="temporal"), ClickHouseUser.DEFAULT, QueryClass.BACKGROUND),
            ("dagster", QueryTags(kind="dagster"), ClickHouseUser.DEFAULT, QueryClass.BACKGROUND),
            ("untagged", QueryTags(), ClickHouseUser.DEFAULT, QueryClass.BACKGROUND),
        ]
    )
    def test_classify_query(
        self, _name: str, tags: QueryTags, ch_user: ClickHouseUser, expected: QueryClass | None
    ) -> None:
        assert classify_query(tags, ch_user) == expected

    @parameterized.expand(
        [
            ("offline", Workload.OFFLINE, 1, False, Pool.OFFLINE),
            ("online", Workload.ONLINE, 1, False, Pool.ONLINE),
            ("no_team", Workload.ONLINE, None, False, Pool.ONLINE),
            ("logs_cluster", Workload.LOGS, 1, False, None),
            ("endpoints_cluster", Workload.ENDPOINTS, 1, False, None),
            ("unresolved_default", Workload.DEFAULT, 1, False, None),
            ("explicit_client", Workload.OFFLINE, 1, True, None),
            ("team_on_dedicated_cluster", Workload.OFFLINE, 7, False, None),
        ]
    )
    @override_settings(CLICKHOUSE_PER_TEAM_SETTINGS={"7": {"host": "dedicated.example.com"}})
    def test_pool_for(
        self, _name: str, workload: Workload, team_id: int | None, explicit_client: bool, expected: Pool | None
    ) -> None:
        assert pool_for(workload=workload, team_id=team_id, explicit_client=explicit_client) == expected
