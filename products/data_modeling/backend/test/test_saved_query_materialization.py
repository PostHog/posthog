from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import ActivityLog, User
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade import api
from products.data_modeling.backend.logic.freshness import UnsatisfiableFrequencyError
from products.data_modeling.backend.logic.incremental import IncrementalConfig
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.test.helpers import warehouse_source_node
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

GET_V2_DAG_IDS = "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids"
DAILY_COUNTS = "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day"
READ_ACCESS_CHECK = "products.data_modeling.backend.logic.saved_query_materialization.assert_user_can_read_query"
DAY_KEY = IncrementalConfig(incremental_key="day", unique_key=("day",))
TIMESTAMP_COLUMN = {"timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime64(6, 'UTC')"}}
HOSTILE_KEY = IncrementalConfig(incremental_key='day"; DROP TABLE events; --', unique_key=("day",))
STORED_DAY_KEY = {"enabled": True, "incremental_key": "day", "unique_key": ["day"], "lookback_seconds": 0}
NODE_MATERIALIZATION_SYNC_CONNECT = "products.data_modeling.backend.logic.node_materialization.sync_connect"


def _name_no_blockers(_bounds: object) -> dict[str, str]:
    return {}


class TestEnableSavedQueryMaterialization(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name=f"posthog_{self.team.id}")
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="event_view",
            query={"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            created_by=self.user,
        )
        self.node = Node.objects.create(
            team=self.team, dag=self.dag, name="event_view", saved_query=self.saved_query, type=NodeType.VIEW
        )

    def _enable(
        self,
        sync_frequency_interval: timedelta,
        user: User | None = None,
        incremental_config: IncrementalConfig | None = None,
    ) -> None:
        api.enable_saved_query_materialization(
            self.team.id,
            self.saved_query.id,
            user=user or self.user,
            sync_frequency_interval=sync_frequency_interval,
            visible_blocker_names=_name_no_blockers,
            was_impersonated=False,
            incremental_config=incremental_config,
        )

    def test_enabling_retypes_the_node_logs_the_change_and_starts_a_run_for_the_user(self) -> None:
        temporal = AsyncMock()
        with (
            patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            patch(NODE_MATERIALIZATION_SYNC_CONNECT, return_value=temporal),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._enable(timedelta(hours=1))

        self.saved_query.refresh_from_db()
        self.node.refresh_from_db()
        activity = ActivityLog.objects.get(item_id=str(self.saved_query.id), activity="materialization_enabled")
        workflow_inputs = temporal.start_workflow.call_args.args[1]
        assert self.saved_query.is_materialized is True
        assert self.node.type == NodeType.MAT_VIEW
        assert activity.user == self.user
        assert activity.detail is not None
        assert activity.detail["changes"][0]["after"] == str(timedelta(hours=1))
        assert workflow_inputs["manually_triggered_by_id"] == self.user.pk

    def test_a_cadence_faster_than_the_source_is_refused_before_anything_is_written(self) -> None:
        source = warehouse_source_node(self.team, self.dag, sync_frequency_interval=timedelta(hours=24))
        Edge.objects.create(team=self.team, dag=self.dag, source=source, target=self.node)

        with (
            patch.object(DataWarehouseSavedQuery, "schedule_materialization") as schedule_materialization,
            self.assertRaises(api.MaterializationRefusedError),
        ):
            self._enable(timedelta(minutes=15))

        self.saved_query.refresh_from_db()
        schedule_materialization.assert_not_called()
        assert self.saved_query.is_materialized is False
        assert self.saved_query.sync_frequency_interval is None

    def test_a_cadence_refused_while_scheduling_restores_the_previous_materialization(self) -> None:
        self.saved_query.is_materialized = True
        self.saved_query.sync_frequency_interval = timedelta(hours=12)
        self.saved_query.save(update_fields=["is_materialized", "sync_frequency_interval"])

        with (
            patch.object(
                DataWarehouseSavedQuery,
                "schedule_materialization",
                side_effect=UnsatisfiableFrequencyError("lineage moved"),
            ),
            self.assertRaises(api.MaterializationRefusedError),
        ):
            self._enable(timedelta(hours=1))

        self.saved_query.refresh_from_db()
        assert self.saved_query.is_materialized is True
        assert self.saved_query.sync_frequency_interval == timedelta(hours=12)

    def test_a_schedule_that_disables_materialization_fails_without_logging_an_enable(self) -> None:
        def disable_materialization(saved_query: DataWarehouseSavedQuery, **_kwargs: object) -> None:
            saved_query.is_materialized = False
            saved_query.save(update_fields=["is_materialized"])

        with (
            patch.object(
                DataWarehouseSavedQuery, "schedule_materialization", autospec=True, side_effect=disable_materialization
            ),
            self.assertRaises(api.MaterializationFailedError),
        ):
            self._enable(timedelta(hours=1))

        self.node.refresh_from_db()
        assert self.node.type == NodeType.VIEW
        assert not ActivityLog.objects.filter(item_id=str(self.saved_query.id)).exists()

    def test_a_user_who_can_only_view_the_saved_query_cannot_materialize_it(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(self.saved_query.id),
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=viewer, organization=self.organization),
        )

        with (
            patch.object(DataWarehouseSavedQuery, "schedule_materialization") as schedule_materialization,
            self.assertRaises(api.MaterializationForbiddenError),
        ):
            self._enable(timedelta(hours=1), user=viewer)

        self.saved_query.refresh_from_db()
        schedule_materialization.assert_not_called()
        assert self.saved_query.is_materialized is False

    @parameterized.expand(
        [
            ("incremental", None, DAY_KEY, STORED_DAY_KEY),
            ("full_refresh_clears_leftover_keys", STORED_DAY_KEY, None, None),
        ]
    )
    def test_the_refresh_mode_is_stored_before_the_first_run(
        self,
        _name: str,
        stored_before: dict | None,
        incremental_config: IncrementalConfig | None,
        expected: dict | None,
    ) -> None:
        self.saved_query.query = {"kind": "HogQLQuery", "query": DAILY_COUNTS}
        self.saved_query.incremental_config = stored_before
        self.saved_query.save(update_fields=["query", "incremental_config"])
        configs_seen_by_the_first_run: list[dict | None] = []

        def record_config(saved_query: DataWarehouseSavedQuery, **_kwargs: object) -> None:
            configs_seen_by_the_first_run.append(
                DataWarehouseSavedQuery.objects.get(id=saved_query.id).incremental_config
            )

        with patch.object(
            DataWarehouseSavedQuery, "schedule_materialization", autospec=True, side_effect=record_config
        ):
            self._enable(timedelta(hours=1), incremental_config=incremental_config)

        assert configs_seen_by_the_first_run == [expected]

    @parameterized.expand([("incremental", DAY_KEY), ("full_refresh", None)])
    def test_a_config_edited_after_the_view_was_read_is_not_overwritten(
        self, _name: str, incremental_config: IncrementalConfig | None
    ) -> None:
        self.saved_query.query = {"kind": "HogQLQuery", "query": DAILY_COUNTS}
        self.saved_query.save(update_fields=["query"])
        edited_config = {**STORED_DAY_KEY, "lookback_seconds": 3600}

        def edit_config_concurrently(*_args: object, **_kwargs: object) -> None:
            DataWarehouseSavedQuery.objects.filter(id=self.saved_query.id).update(incremental_config=edited_config)

        with (
            patch(READ_ACCESS_CHECK, side_effect=edit_config_concurrently),
            patch.object(DataWarehouseSavedQuery, "schedule_materialization") as schedule_materialization,
            self.assertRaises(api.IncrementalConfigRefusedError),
        ):
            self._enable(timedelta(hours=1), incremental_config=incremental_config)

        self.saved_query.refresh_from_db()
        schedule_materialization.assert_not_called()
        assert self.saved_query.incremental_config == edited_config

    @parameterized.expand(
        [
            ("limit_in_its_own_query", None, None, DAY_KEY, False),
            (
                "limit_inside_a_view_it_reads",
                "SELECT timestamp FROM events ORDER BY timestamp DESC LIMIT 100",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM recent_events GROUP BY day",
                DAY_KEY,
                False,
            ),
            (
                "limit_inside_a_materialized_view_it_reads",
                "SELECT timestamp FROM events ORDER BY timestamp DESC LIMIT 100",
                "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM recent_events GROUP BY day",
                DAY_KEY,
                True,
            ),
            ("key_that_is_not_an_output_column", None, DAILY_COUNTS, HOSTILE_KEY, False),
        ]
    )
    def test_an_incremental_config_the_query_forbids_is_refused_before_anything_is_written(
        self,
        _name: str,
        upstream_query: str | None,
        query: str | None,
        incremental_config: IncrementalConfig,
        upstream_materialized: bool,
    ) -> None:
        if upstream_query is not None:
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name="recent_events",
                query={"kind": "HogQLQuery", "query": upstream_query},
                columns=TIMESTAMP_COLUMN,
                is_materialized=upstream_materialized,
                table=DataWarehouseTable.objects.create(
                    team=self.team, name="recent_events_tbl", format="Delta", columns=TIMESTAMP_COLUMN
                )
                if upstream_materialized
                else None,
            )
        if query is not None:
            self.saved_query.query = {"kind": "HogQLQuery", "query": query}
            self.saved_query.save(update_fields=["query"])

        with (
            patch.object(DataWarehouseSavedQuery, "schedule_materialization") as schedule_materialization,
            self.assertRaises(api.IncrementalConfigRefusedError),
        ):
            self._enable(timedelta(hours=1), incremental_config=incremental_config)

        self.saved_query.refresh_from_db()
        schedule_materialization.assert_not_called()
        assert self.saved_query.is_materialized is False
        assert self.saved_query.incremental_config is None
