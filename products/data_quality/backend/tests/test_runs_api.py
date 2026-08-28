from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.test.db_context_capturing import capture_db_queries

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node
from products.data_quality.backend.facade import api
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckType, SubjectStatus, SubjectType
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

START_SUITE = "products.data_quality.backend.logic.checks.sync_connect"
FLAG = "products.data_quality.backend.presentation.views.is_data_quality_checks_enabled"


class TestDataQualityRunAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.orders = self._make_view("orders")
        self.customers = self._make_view("customers")
        self.url = f"/api/projects/{self.team.id}/data_quality_runs/"
        self.checks_url = f"/api/projects/{self.team.id}/data_quality_checks/"
        flag = patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _make_view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

    def _check(self, view: DataWarehouseSavedQuery, **overrides) -> DataQualityCheck:
        return DataQualityCheck.objects.for_team(self.team.id).create(
            **{
                "team": self.team,
                "subject_type": SubjectType.VIEW,
                "saved_query_id": view.id,
                "subject_name": view.name,
                "check_type": CheckType.NOT_NULL,
                "column_name": "id",
                "fingerprint": uuid4().hex,
                **overrides,
            }
        )

    def _run(self, **body):
        with patch(START_SUITE, return_value=MagicMock(start_workflow=AsyncMock())):
            return self.client.post(self.url, body, format="json")

    def _deny_orders(self) -> None:
        self._deny(self.orders)

    def _deny(self, *views: DataWarehouseSavedQuery) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        for view in views:
            AccessControl.objects.create(
                team=self.team,
                resource="warehouse_view",
                resource_id=str(view.id),
                organization_member=self.organization_membership,
                access_level="none",
            )
        warehouse_ac = patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda name, *a, **k: name == "hogql-warehouse-access-control",
        )
        warehouse_ac.start()
        self.addCleanup(warehouse_ac.stop)
        cache.clear()

    def test_running_with_no_selection_runs_every_enabled_check(self) -> None:
        self._check(self.orders)
        self._check(self.customers)
        self._check(self.customers, column_name="total", enabled=False)

        response = self._run()

        assert response.status_code == status.HTTP_200_OK, response.json()
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=response.json()["id"])
        assert suite_run.status == "running"
        # A sweep has no single subject, so the response has to say so rather than name one.
        assert response.json()["subject_type"] is None

    def test_a_sweep_leaves_out_checks_on_a_denied_subject(self) -> None:
        # "Everything" means everything this member can see. A denied subject is not part of it.
        mine = self._check(self.customers)
        self._check(self.orders)
        self._deny_orders()

        with (
            patch("products.data_quality.backend.presentation.views.api.start_check_suite") as start,
            patch(START_SUITE, return_value=MagicMock(start_workflow=AsyncMock())),
        ):
            start.return_value = DataQualitySuiteRun.objects.for_team(self.team.id).create(
                team=self.team, trigger="manual"
            )
            self.client.post(self.url, {}, format="json")

        assert start.call_args.kwargs["check_ids"] == [str(mine.id)]

    @parameterized.expand([("every_check_is_denied",), ("named_ids_match_nothing_runnable",)])
    def test_a_run_with_nothing_to_run_starts_no_workflow(self, case: str) -> None:
        # An empty selection is indistinguishable from no selector by the time it reaches the
        # worker, so handing one over sweeps the whole project instead of running none of it.
        body: dict = {}
        if case == "every_check_is_denied":
            self._check(self.orders)
            self._deny_orders()
        else:
            self._check(self.customers)
            body = {"check_ids": [str(uuid4())]}

        with patch(START_SUITE) as connect:
            response = self.client.post(self.url, body, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["status"] == "empty"
        connect.assert_not_called()

    def test_naming_a_denied_check_is_refused(self) -> None:
        # Naming one is an attempt to read it, so it 403s rather than being silently dropped.
        denied = self._check(self.orders)
        self._deny_orders()

        response = self._run(check_ids=[str(denied.id)])

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("named",), ("swept",)])
    def test_a_denied_subject_renamed_since_its_last_run_is_still_not_run_against(self, case: str) -> None:
        # This route is the one that actually executes the query, so matching denial against the name
        # stamped on the check would run it against the denied view for the whole window after a
        # rename, and hand the pass/fail and row counts back through the suite report.
        denied = self._check(self.orders, subject_name="orders_legacy")
        self._deny_orders()

        with patch(START_SUITE) as connect:
            body = {"check_ids": [str(denied.id)]} if case == "named" else {}
            response = self.client.post(self.url, body, format="json")

        if case == "named":
            assert response.status_code == status.HTTP_403_FORBIDDEN
        else:
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json()["status"] == "empty"
        connect.assert_not_called()

    def test_the_sweep_is_gated_on_the_feature_flag(self) -> None:
        with patch(FLAG, return_value=False):
            assert self.client.post(self.url, {}, format="json").status_code == status.HTTP_403_FORBIDDEN

    def test_query_denied_members_cannot_sweep_or_read_runs(self) -> None:
        AccessControl.objects.create(team=self.team, resource="query", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()

        assert self.client.post(self.url, {}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN

    def test_history_serves_the_sweeps_the_per_subject_surfaces_hide(self) -> None:
        # The nested suite-run lists filter on subject_uuid, so a multi-subject sweep is only
        # readable here.
        sweep = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        scoped = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="materialization", subject_type=SubjectType.VIEW, subject_uuid=self.orders.id
        )

        listed = self.client.get(self.url)

        assert {row["id"] for row in listed.json()["results"]} == {str(sweep.id), str(scoped.id)}
        assert self.client.get(f"{self.url}{sweep.id}/").status_code == status.HTTP_200_OK

    def test_history_withholds_the_suites_that_report_on_a_denied_subject(self) -> None:
        # A suite row carries its subject and its outcome counters, so serving one is serving counts
        # over rows the member cannot read. The nested lists are gated by their parent; this one
        # spans every subject and has none.
        self._check(self.orders)
        mine = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="materialization", subject_type=SubjectType.VIEW, subject_uuid=self.customers.id
        )
        denied = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="materialization", subject_type=SubjectType.VIEW, subject_uuid=self.orders.id
        )
        sweep = self._sweep_covering(self.orders)
        self._deny_orders()

        listed = self.client.get(self.url)

        assert {row["id"] for row in listed.json()["results"]} == {str(mine.id)}
        assert self.client.get(f"{self.url}{denied.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(f"{self.url}{sweep.id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_history_withholds_a_suite_whose_run_read_a_denied_subject(self) -> None:
        # The run sits on the allowed subject, so its own uuid clears the filter. What it read is in
        # the identities it pinned, and the counters report on those rows too.
        suite_run = self._suite_reading(self.orders)
        self._check(self.orders)
        self._deny_orders()

        listed = self.client.get(self.url)

        assert [row["id"] for row in listed.json()["results"]] == []
        assert self.client.get(f"{self.url}{suite_run.id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_history_withholds_a_suite_whose_subject_was_recreated_under_the_same_name(self) -> None:
        # Deleting "orders" frees its name, so a member can create their own and make the name resolve
        # for them again. Matched by name, the suite reporting on the run that read the original would
        # list, carrying its counters over rows the member still cannot read.
        secrets = self._make_view("secrets")
        suite_run = self._suite_reading(self.orders)
        self._deny(self.orders, secrets)
        self.orders.delete()
        self._make_view("orders")

        listed = self.client.get(self.url)

        assert [row["id"] for row in listed.json()["results"]] == []
        assert self.client.get(f"{self.url}{suite_run.id}/").status_code == status.HTTP_404_NOT_FOUND

    def _suite_reading(self, read: DataWarehouseSavedQuery) -> DataQualitySuiteRun:
        """A suite whose one run sits on the allowed "customers" but read another subject."""
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            suite_run=suite_run,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.customers.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            check_config={"query": f"SELECT 1 FROM {read.name}"},
            referenced_subjects=[{"subject_type": str(SubjectType.VIEW), "subject_uuid": str(read.id)}],
            check_fingerprint=uuid4().hex,
            status=CheckRunStatus.FAILED,
        )
        return suite_run

    def _sweep_covering(self, view: DataWarehouseSavedQuery) -> DataQualitySuiteRun:
        """A multi-subject sweep whose counters include one check run against this view."""
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            suite_run=suite_run,
            subject_type=SubjectType.VIEW,
            subject_uuid=view.id,
            subject_name=view.name,
            check_type=CheckType.NOT_NULL,
            check_fingerprint=uuid4().hex,
            status=CheckRunStatus.FAILED,
        )
        return suite_run

    def test_the_overview_lists_every_subjects_checks(self) -> None:
        # The nested surfaces each serve one parent, so this is the only list that spans subjects.
        self._check(self.orders)
        self._check(self.customers)

        response = self.client.get(self.checks_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert {row["subject_name"] for row in response.json()["results"]} == {"orders", "customers"}

    def test_the_overview_hides_a_denied_subjects_checks(self) -> None:
        # A list of everything is a directory of the project's tables, so a denied one must not
        # appear in it, nor in the health rollup derived from the same set.
        self._check(self.orders)
        self._check(self.customers)
        self._deny_orders()

        listed = self.client.get(self.checks_url)
        health = self.client.get(f"{self.checks_url}health/")

        assert {row["subject_name"] for row in listed.json()["results"]} == {"customers"}
        assert {row["subject_uuid"] for row in health.json()} == {str(self.customers.id)}

    def test_the_overview_hides_a_check_that_reads_a_denied_subject(self) -> None:
        # The parent is allowed, but the config names "orders" and the status answers questions
        # about its rows, so listing the check is a directory entry for a table the member cannot read.
        self._check(
            self.customers,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT 1 FROM orders"},
        )
        self._deny_orders()

        listed = self.client.get(self.checks_url)
        health = self.client.get(f"{self.checks_url}health/")

        assert listed.json()["results"] == []
        assert health.json() == []

    def test_the_overview_hides_a_check_whose_last_run_read_a_recreated_subject(self) -> None:
        # Deleting the denied "orders" empties the denial set and frees its name, so the config now
        # names something the member may read. The status beside it is still the verdict of a run
        # against the original, which is what the identities the run pinned still answer for.
        reader = self._check(
            self.customers,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT 1 FROM orders"},
            last_status=CheckRunStatus.FAILED,
        )
        DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            suite_run=DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual"),
            quality_check=reader,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.customers.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            check_config=reader.config,
            referenced_subjects=[{"subject_type": str(SubjectType.VIEW), "subject_uuid": str(self.orders.id)}],
            check_fingerprint=reader.fingerprint,
            status=CheckRunStatus.FAILED,
        )
        self._deny_orders()
        self.orders.delete()
        self._make_view("orders")

        listed = self.client.get(self.checks_url)
        health = self.client.get(f"{self.checks_url}health/")

        assert listed.json()["results"] == []
        assert health.json() == []

    def test_the_overview_hides_a_denied_subject_renamed_since_its_last_run(self) -> None:
        # subject_name is only rewritten when the check runs, so matching denial against it serves
        # the subject's checks for the whole window between a rename and the next run.
        self._check(self.orders, subject_name="orders_legacy")
        self._deny_orders()

        listed = self.client.get(self.checks_url)

        assert listed.json()["results"] == []

    def test_the_overview_leaves_out_orphans_but_keeps_their_history(self) -> None:
        # An orphan has no subject page to link to, nothing to run, and no rollup to sit under, so
        # showing it in the project list would be a dead row.
        live = self._check(self.customers)
        orphan = self._check(self.orders, subject_status=SubjectStatus.ORPHANED)

        listed = self.client.get(self.checks_url)
        health = self.client.get(f"{self.checks_url}health/")

        assert {row["id"] for row in listed.json()["results"]} == {str(live.id)}
        assert {row["subject_uuid"] for row in health.json()} == {str(self.customers.id)}
        assert DataQualityCheck.objects.for_team(self.team.id).filter(id=orphan.id).exists()

    def test_the_overview_says_where_each_subject_can_be_opened(self) -> None:
        # The row links to the subject's own page, which lives on a DAG node for a view and on a
        # source schema for a synced table -- neither of which the check row itself carries.
        node = Node.objects.create(team=self.team, dag=DAG.get_or_create_default(self.team), saved_query=self.orders)
        table, schema = self._synced_table("stripe_charges")
        self._check(self.orders)
        self._check(self.customers)
        self._check(
            self.orders, subject_type=SubjectType.TABLE, saved_query_id=None, table_id=table.id, subject_name=table.name
        )

        rows = {row["subject_name"]: row for row in self.client.get(self.checks_url).json()["results"]}

        assert rows["orders"]["subject_node_id"] == str(node.id)
        assert rows["orders"]["subject_source_id"] is None
        assert rows["stripe_charges"]["subject_source_id"] == str(schema.source_id)
        assert rows["stripe_charges"]["subject_schema_id"] == str(schema.id)
        # A view on no DAG has no node page; the row renders its name as plain text.
        assert rows["customers"]["subject_node_id"] is None

    def test_the_overview_authorizes_a_definition_once_however_many_checks_share_it(self) -> None:
        # The overview lists every check in the project unpaginated, so authorizing a definition per
        # row costs a query per row for every relationships check and a HogQL parse per custom_sql
        # one. The verdict depends on the definition alone, so the extra rows must cost nothing.
        target = self._make_view("targets")
        config = {"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(target.id), "to_column": "id"}
        self._deny_orders()
        self._sharing_checks(config, count=1)
        # Warms the instance settings and team config the first request of any test would pay for.
        self.client.get(self.checks_url)

        with capture_db_queries() as one_check:
            assert self.client.get(self.checks_url).status_code == status.HTTP_200_OK
        self._sharing_checks(config, count=5)
        with capture_db_queries() as six_checks:
            listed = self.client.get(self.checks_url)

        assert len(listed.json()["results"]) == 6
        assert len(six_checks.captured_queries) == len(one_check.captured_queries)

    def _sharing_checks(self, config: dict, count: int) -> None:
        """Checks on the allowed subject that all read the same second subject."""
        for _ in range(count):
            self._check(
                self.customers,
                check_type=CheckType.RELATIONSHIPS,
                column_name=f"customer_{uuid4().hex[:8]}",
                config=config,
            )

    def test_resolving_where_subjects_live_does_not_grow_with_the_project(self) -> None:
        # The overview lists every check in the project, so a query per row is a query per table in
        # the warehouse.
        views = [self._check(self._make_view(f"view_{index}")) for index in range(5)]
        tables = [
            self._check(
                self.orders,
                subject_type=SubjectType.TABLE,
                saved_query_id=None,
                table_id=self._synced_table(f"table_{index}")[0].id,
            )
            for index in range(5)
        ]

        with self.assertNumQueries(2):
            located = api.subject_locations(self.team.id, [*views, *tables])

        assert len(located) == 5

    def _synced_table(self, name: str) -> tuple[DataWarehouseTable, ExternalDataSchema]:
        source = ExternalDataSource.objects.create(team=self.team, source_type="Stripe")
        table = DataWarehouseTable.objects.create(
            team=self.team, name=name, format=DataWarehouseTable.TableFormat.Parquet, url_pattern=""
        )
        schema = ExternalDataSchema.objects.create(team=self.team, source=source, table=table, name=name)
        return table, schema

    def test_health_rolls_up_each_subject_without_a_query_per_subject(self) -> None:
        self._check(self.orders, last_status=CheckRunStatus.FAILED)
        self._check(self.orders, column_name="total", last_status=CheckRunStatus.PASSED)
        self._check(self.customers, last_status=CheckRunStatus.PASSED)

        response = self.client.get(f"{self.checks_url}health/")

        by_subject = {row["subject_uuid"]: row for row in response.json()}
        assert by_subject[str(self.orders.id)] == {
            "subject_type": "view",
            "subject_uuid": str(self.orders.id),
            "health": "failing",
            "checks_total": 2,
            "checks_failing": 1,
        }
        assert by_subject[str(self.customers.id)]["health"] == "healthy"
