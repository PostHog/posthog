from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.db_context_capturing import capture_db_queries

from products.access_control.backend.models.access_control import AccessControl
from products.data_catalog.backend.facade.models import Metric
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Node
from products.data_quality.backend.facade import api
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckType, SubjectStatus, SubjectType
from products.data_quality.backend.models import DataQualityCheck, DataQualitySuiteRun
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

    def _materialize(self, view: DataWarehouseSavedQuery) -> DataWarehouseTable:
        backing_table = DataWarehouseTable.objects.create(
            team=self.team,
            name=view.name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=f"s3://bucket/{view.folder_path}/{view.normalized_name}",
        )
        view.table = backing_table
        view.is_materialized = True
        view.save(update_fields=["table", "is_materialized"])
        return backing_table

    def _metric(self, name: str) -> Metric:
        return Metric.objects.for_team(self.team.id).create(
            team=self.team,
            name=name,
            definition={"kind": "HogQLQuery", "query": "SELECT 1 AS value"},
            referenced_table_names=[],
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

    def _authenticate_token(self, kind: str, scopes: list[str]) -> None:
        if kind == "pat":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=self.user, label="Data quality", secure_value=hash_key_value(token), scopes=scopes
            )
        else:
            application = OAuthApplication.objects.create(
                name="Data quality",
                user=self.user,
                organization=self.organization,
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
            )
            token = f"pha_{uuid4().hex}"
            OAuthAccessToken.objects.create(
                user=self.user,
                application=application,
                token=token,
                expires=timezone.now() + timedelta(hours=1),
                scope=" ".join(scopes),
            )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @parameterized.expand(
        [
            (kind, resource, admin)
            for kind in ("pat", "oauth")
            for resource in ("warehouse_objects", "data_catalog")
            for admin in (False, True)
        ]
    )
    def test_project_endpoints_filter_token_subjects(self, kind: str, resource: str, admin: bool) -> None:
        warehouse_check = self._check(self.orders)
        metric = self._metric("signups")
        metric_check = self._check(
            self.orders,
            saved_query_id=None,
            metric_id=metric.id,
            subject_type=SubjectType.METRIC,
            subject_name=metric.name,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT * FROM {metric}"},
        )
        allowed, denied = (
            (warehouse_check, metric_check) if resource == "warehouse_objects" else (metric_check, warehouse_check)
        )
        suites = []
        for check in (allowed, denied):
            assert check.subject_uuid is not None
            suites.append(
                DataQualitySuiteRun.objects.for_team(self.team.id).create(
                    team=self.team,
                    trigger="manual",
                    subject_type=check.subject_type,
                    subject_uuid=check.subject_uuid,
                )
            )
        mixed = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        for check in (allowed, denied):
            assert check.subject_uuid is not None
            api.record_check_run(
                self.team.id,
                suite_run=mixed,
                quality_check=check,
                subject_type=check.subject_type,
                subject_uuid=check.subject_uuid,
                subject_name=check.subject_name,
                check_type=check.check_type,
                check_fingerprint=check.fingerprint,
                status=CheckRunStatus.PASSED,
                referenced_subjects=[],
            )
        if admin:
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save(update_fields=["level"])
        self._authenticate_token(kind, [f"{resource}:write", "query:read"])

        listed = self.client.get(self.checks_url)
        assert listed.status_code == 200, listed.json()
        assert listed.json()["count"] == 1
        assert [check["id"] for check in listed.json()["results"]] == [str(allowed.id)]
        health = self.client.get(f"{self.checks_url}health/")
        assert health.status_code == 200, health.json()
        assert [row["subject_type"] for row in health.json()] == [allowed.subject_type]
        history = self.client.get(self.url)
        assert history.status_code == 200, history.json()
        assert [suite["id"] for suite in history.json()["results"]] == [str(suites[0].id)]
        assert self.client.get(f"{self.url}{suites[1].id}/").status_code == 404
        assert self._run(check_ids=[str(denied.id)]).status_code == 403
        assert self._run(check_ids=[str(allowed.id)]).status_code == 200
        temporal = MagicMock(start_workflow=AsyncMock())
        with patch(START_SUITE, return_value=temporal):
            swept = self.client.post(self.url, {}, format="json")
        assert swept.status_code == 200, swept.json()
        assert temporal.start_workflow.call_args.args[1]["check_ids"] == [str(allowed.id)]

    @parameterized.expand([(kind, admin) for kind in ("pat", "oauth") for admin in (False, True)])
    def test_catalog_token_cannot_read_warehouse_through_a_metric_check(self, kind: str, admin: bool) -> None:
        metric = self._metric("signups")
        check = self._check(
            self.orders,
            saved_query_id=None,
            metric_id=metric.id,
            subject_type=SubjectType.METRIC,
            subject_name=metric.name,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT * FROM {metric} JOIN orders ON 1 = 1"},
        )
        if admin:
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save(update_fields=["level"])
        self._authenticate_token(kind, ["data_catalog:write", "query:read"])
        listed = self.client.get(self.checks_url)
        assert listed.status_code == 200
        assert listed.json()["results"] == []
        assert self.client.get(f"{self.checks_url}health/").json() == []
        assert self._run(check_ids=[str(check.id)]).status_code == 403
        temporal = MagicMock(start_workflow=AsyncMock())
        with patch(START_SUITE, return_value=temporal):
            swept = self.client.post(self.url, {}, format="json")
        assert swept.status_code == 200
        temporal.start_workflow.assert_not_called()
        nested_url = f"/api/projects/{self.team.id}/data_catalog/metrics/{metric.id}/checks/"
        nested = self.client.get(nested_url)
        assert nested.status_code == 200
        assert nested.json()["results"] == []
        with patch(START_SUITE, return_value=temporal):
            assert self.client.post(f"{nested_url}{check.id}/run/").status_code == 403

    @parameterized.expand(
        [
            (["query:read", "data_catalog:read"], 200, 403),
            (["query:read"], 403, 403),
            (["data_catalog:write"], 403, 403),
            (["*"], 200, 200),
        ]
    )
    def test_project_subject_scope_requirements(self, scopes: list[str], read_status: int, write_status: int) -> None:
        self._authenticate_token("pat", scopes)
        assert self.client.get(self.checks_url).status_code == read_status
        assert self._run().status_code == write_status

    @parameterized.expand(
        [
            (kind, subject_type, level)
            for kind in ("pat", "oauth")
            for subject_type in ("table", "view")
            for level in ("read", "write")
        ]
    )
    def test_nested_warehouse_routes_honor_their_own_scopes(self, kind: str, subject_type: str, level: str) -> None:
        subject: DataWarehouseSavedQuery | DataWarehouseTable
        if subject_type == "table":
            subject = DataWarehouseTable.objects.create(team=self.team, name="purchases", format="Parquet")
            check = self._check(self.orders, subject_type=SubjectType.TABLE, saved_query_id=None, table_id=subject.id)
            path = "warehouse_tables"
        else:
            subject = self.orders
            check = self._check(self.orders)
            path = "warehouse_saved_queries"
        nested = f"/api/projects/{self.team.id}/{path}/{subject.id}/checks/"
        self._authenticate_token(kind, [f"warehouse_{subject_type}:{level}", "query:read"])

        listed = self.client.get(nested)
        assert listed.status_code == 200, listed.json()
        assert [row["id"] for row in listed.json()["results"]] == [str(check.id)]
        assert self.client.get(f"{nested}{check.id}/runs/").status_code == 200
        with patch(START_SUITE, return_value=MagicMock(start_workflow=AsyncMock())):
            assert self.client.post(f"{nested}{check.id}/run/").status_code == (200 if level == "write" else 403)
        assert self.client.get(self.checks_url).status_code == 403

    def test_catalog_only_members_see_teammates_metric_checks_and_suites(self) -> None:
        author = self._create_user("metric-author@example.com")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_objects",
            organization_member=self.organization_membership,
            access_level="none",
        )
        metric = self._metric("active_users")
        check = self._check(
            self.orders,
            subject_type=SubjectType.METRIC,
            saved_query_id=None,
            metric_id=metric.id,
            subject_name=metric.name,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT * FROM {metric}"},
            created_by=author,
        )
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.METRIC, subject_uuid=metric.id, created_by=author
        )
        self._check(self.orders)
        cache.clear()
        nested = f"/api/projects/{self.team.id}/data_catalog/metrics/{metric.id}/"

        for url in (self.checks_url, f"{nested}checks/"):
            response = self.client.get(url)
            assert response.status_code == 200, response.json()
            assert [row["id"] for row in response.json()["results"]] == [str(check.id)]
        for url in (self.url, f"{nested}check_suite_runs/"):
            response = self.client.get(url)
            assert response.status_code == 200, response.json()
            assert [row["id"] for row in response.json()["results"]] == [str(suite.id)]

    @parameterized.expand(
        [
            (subject_type, access_level, enforce_warehouse_access)
            for subject_type in (SubjectType.TABLE, SubjectType.VIEW)
            for access_level in ("viewer", "editor")
            for enforce_warehouse_access in (False, True)
        ]
    )
    def test_specific_warehouse_grants_apply_to_check_routes(
        self, subject_type: SubjectType, access_level: str, enforce_warehouse_access: bool
    ) -> None:
        author = self._create_user("check-author@example.com")
        subjects: list[DataWarehouseSavedQuery | DataWarehouseTable]
        if subject_type == SubjectType.TABLE:
            subjects = [
                DataWarehouseTable.objects.create(team=self.team, name=name, format="Parquet", created_by=author)
                for name in ("granted_table", "ungranted_table")
            ]
            subject_fk = "table_id"
            parent_path = "warehouse_tables"
        else:
            subjects = [self.orders, self.customers]
            DataWarehouseSavedQuery.objects.filter(team=self.team, id__in=[subject.id for subject in subjects]).update(
                created_by=author
            )
            subject_fk = "saved_query_id"
            parent_path = "warehouse_saved_queries"
        granted, ungranted = [
            self._check(
                self.orders,
                subject_type=subject_type,
                subject_name=subject.name,
                created_by=author,
                **{"saved_query_id": None, subject_fk: subject.id},
            )
            for subject in subjects
        ]
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource=f"warehouse_{subject_type}",
            resource_id=str(subjects[0].id),
            organization_member=self.organization_membership,
            access_level=access_level,
        )
        allowed_suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team,
            trigger="manual",
            created_by=author,
            subject_type=subject_type,
            subject_uuid=granted.subject_uuid,
        )
        mixed_suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", created_by=author
        )
        for check in (granted, ungranted):
            assert check.subject_uuid is not None
            api.record_check_run(
                self.team.id,
                suite_run=mixed_suite,
                quality_check=check,
                subject_type=subject_type,
                subject_uuid=check.subject_uuid,
                subject_name=check.subject_name,
                check_type=check.check_type,
                check_fingerprint=check.fingerprint,
                referenced_subjects=[],
                status=CheckRunStatus.PASSED,
            )
        cache.clear()
        flag = patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda name, *args, **kwargs: (
                enforce_warehouse_access and name == "hogql-warehouse-access-control"
            ),
        )
        flag.start()
        self.addCleanup(flag.stop)
        nested = f"/api/projects/{self.team.id}/{parent_path}/{subjects[0].id}/checks/"
        denied_nested = f"/api/projects/{self.team.id}/{parent_path}/{subjects[1].id}/checks/"

        for url in (nested, self.checks_url):
            listed = self.client.get(url)
            assert listed.status_code == status.HTTP_200_OK, listed.json()
            assert listed.json()["count"] == 1
            assert [row["id"] for row in listed.json()["results"]] == [str(granted.id)]
        assert self.client.get(denied_nested).status_code == status.HTTP_403_FORBIDDEN
        history = self.client.get(self.url)
        assert history.status_code == status.HTTP_200_OK, history.json()
        assert [suite["id"] for suite in history.json()["results"]] == [str(allowed_suite.id)]
        assert self.client.get(f"{self.url}{mixed_suite.id}/").status_code == status.HTTP_404_NOT_FOUND

        temporal = MagicMock(start_workflow=AsyncMock())
        with patch(START_SUITE, return_value=temporal):
            assert self.client.post(f"{denied_nested}{ungranted.id}/run/").status_code == status.HTTP_403_FORBIDDEN
            denied_selection = self.client.post(self.url, {"check_ids": [str(ungranted.id)]}, format="json")
            assert denied_selection.status_code == status.HTTP_403_FORBIDDEN, denied_selection.json()
            temporal.start_workflow.assert_not_called()

            expected_status = status.HTTP_200_OK if access_level == "editor" else status.HTTP_403_FORBIDDEN
            nested_run = self.client.post(f"{nested}{granted.id}/run/")
            assert nested_run.status_code == expected_status, nested_run.json()
            selected_run = self.client.post(self.url, {"check_ids": [str(granted.id)]}, format="json")
            assert selected_run.status_code == expected_status, selected_run.json()
        assert temporal.start_workflow.call_count == (2 if access_level == "editor" else 0)

    @parameterized.expand([("metric",), ("view",)])
    def test_deleted_subject_checks_disappear_immediately(self, kind: str) -> None:
        subject = self._metric("signups") if kind == "metric" else self.orders
        if kind == "metric":
            self._check(self.orders, saved_query_id=None, metric_id=subject.id, subject_type=SubjectType.METRIC)
        else:
            self._check(self.orders)
        subject.deleted = True
        subject.save(update_fields=["deleted"])
        assert self.client.get(self.checks_url).json()["results"] == []
        assert self.client.get(f"{self.checks_url}health/").json() == []
        assert self._run().json()["status"] == "empty"

    @parameterized.expand([("unrestricted", False), ("restricted", True)])
    def test_running_with_no_selection_runs_every_enabled_check(self, _name: str, restricted: bool) -> None:
        enabled = [self._check(self.orders), self._check(self.customers)]
        enabled.extend(self._check(self._make_view(f"view_{index}")) for index in range(4))
        metrics = [self._metric(f"metric_{index}") for index in range(3)]
        enabled.extend(
            self._check(
                self.orders,
                subject_type=SubjectType.METRIC,
                saved_query_id=None,
                metric_id=metric.id,
                subject_name=metric.name,
                check_type=CheckType.CUSTOM_SQL,
                column_name="",
                config={"query": "SELECT * FROM {metric} WHERE value < 1"},
            )
            for metric in metrics
            for _ in range(2)
        )
        self._check(self.customers, column_name="total", enabled=False)
        if restricted:
            self._deny(self._make_view("secrets"))

        temporal = MagicMock(start_workflow=AsyncMock())
        with patch(START_SUITE, return_value=temporal), capture_db_queries() as captured:
            response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=response.json()["id"])
        assert suite_run.status == "running"
        # A sweep has no single subject, so the response has to say so rather than name one.
        assert response.json()["subject_type"] is None
        assert set(temporal.start_workflow.call_args.args[1]["check_ids"]) == {str(check.id) for check in enabled}
        statements = [query["sql"] for query in captured.captured_queries]
        metric_definition_reads = [
            sql
            for sql in statements
            if '"data_catalog_metric"."definition"' in sql and '"data_catalog_metric"."id" IN (' in sql
        ]
        assert len(metric_definition_reads) == int(restricted), metric_definition_reads
        assert not any('"posthog_datawarehousesavedquery"."id" =' in sql for sql in statements)

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

    @parameterized.expand([("named",), ("swept",)])
    def test_run_selection_respects_denied_references(self, selection: str) -> None:
        check = self._check(
            self.customers,
            check_type=CheckType.CUSTOM_SQL,
            column_name="",
            config={"query": "SELECT * FROM orders"},
        )
        self._deny_orders()
        body = {"check_ids": [str(check.id)]} if selection == "named" else {}
        response = self._run(**body)
        assert response.status_code == (403 if selection == "named" else 200), response.json()
        if selection == "swept":
            assert response.json()["status"] == "empty"

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

    @parameterized.expand([("unrestricted_member", False), ("restricted_member", True)])
    def test_history_serves_the_sweeps_the_per_subject_surfaces_hide(self, _name: str, restricted: bool) -> None:
        # The nested suite-run lists filter on subject_uuid, so a multi-subject sweep is only readable
        # here. A sweep records no subject of its own, so the subject gate must skip it rather than
        # read the empty column as a subject nobody may see.
        sweep = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        scoped = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="materialization", subject_type=SubjectType.VIEW, subject_uuid=self.orders.id
        )
        if restricted:
            self._deny(self._make_view("secrets"))

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

    def test_history_withholds_a_backing_table_reference_after_its_view_is_renamed(self) -> None:
        backing_table = self._materialize(self.orders)
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        api.record_check_run(
            self.team.id,
            suite_run=suite_run,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.customers.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            check_config={"query": "SELECT 1 FROM orders"},
            referenced_subjects=[{"subject_type": str(SubjectType.TABLE), "subject_uuid": str(backing_table.id)}],
            check_fingerprint=uuid4().hex,
            status=CheckRunStatus.FAILED,
        )
        self.orders.name = "orders_v2"
        self.orders.save(update_fields=["name"])
        self._deny(self.orders)

        listed = self.client.get(self.url)

        assert listed.json()["results"] == []
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

    def test_history_withholds_a_suite_whose_run_declared_a_recreated_denied_subject(self) -> None:
        # A run's own subject was deleted and its name taken by a denied object. The suite reporting
        # on it still carries counters over the original's rows, so the freed name being reused by
        # something denied has to withhold it -- matched by the name the run stamped, not its id.
        temp = self._make_view("temp_orders")
        suite_run = self._sweep_covering(temp)
        temp.delete()
        self._deny(self._make_view("temp_orders"))

        listed = self.client.get(self.url)

        assert [row["id"] for row in listed.json()["results"]] == []
        assert self.client.get(f"{self.url}{suite_run.id}/").status_code == status.HTTP_404_NOT_FOUND

    def _suite_reading(self, read: DataWarehouseSavedQuery) -> DataQualitySuiteRun:
        """A suite whose one run sits on the allowed "customers" but read another subject."""
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        api.record_check_run(
            self.team.id,
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
        api.record_check_run(
            self.team.id,
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

    def test_catalog_only_overview_filters_before_scanning_and_paginating(self) -> None:
        page_size = 150
        visible_count = 205
        visibility_batch_size = 200
        metrics = [self._metric(f"metric_{index}") for index in range(3)]
        visible_checks = [
            DataQualityCheck(
                team=self.team,
                subject_type=SubjectType.METRIC,
                metric_id=metrics[index % len(metrics)].id,
                subject_name=metrics[index % len(metrics)].name,
                check_type=CheckType.CUSTOM_SQL,
                config={"query": "SELECT * FROM {metric} WHERE value < 1"},
                name=f"visible_{index:03d}",
                fingerprint=uuid4().hex,
                created_by=self.user,
                owner=self.user,
            )
            for index in range(visible_count)
        ]
        hidden_warehouse_checks = [
            DataQualityCheck(
                team=self.team,
                subject_type=SubjectType.VIEW,
                saved_query_id=self.orders.id,
                subject_name=self.orders.name,
                check_type=CheckType.NOT_NULL,
                column_name="id",
                name=f"hidden_{index:03d}",
                fingerprint=uuid4().hex,
            )
            for index in range(visible_count)
        ]
        DataQualityCheck.objects.for_team(self.team.id).bulk_create([*visible_checks, *hidden_warehouse_checks])
        for metric in metrics:
            self._check(
                self.orders,
                subject_type=SubjectType.METRIC,
                saved_query_id=None,
                metric_id=metric.id,
                subject_name=metric.name,
                name=f"hidden_reference_{metric.name}",
                check_type=CheckType.CUSTOM_SQL,
                column_name="",
                config={"query": "SELECT * FROM {metric} CROSS JOIN orders"},
            )
        self._deny_orders()
        self._authenticate_token("pat", ["data_catalog:read", "query:read"])
        expected = sorted(visible_checks, key=lambda check: (check.subject_name, check.name))
        visible_ids = {str(check.id) for check in visible_checks}

        for offset in (0, page_size):
            with capture_db_queries() as captured:
                response = self.client.get(self.checks_url, {"limit": page_size, "offset": offset})
            assert response.status_code == status.HTTP_200_OK, response.json()
            body = response.json()
            assert body["count"] == visible_count
            assert [row["id"] for row in body["results"]] == [
                str(check.id) for check in expected[offset : offset + page_size]
            ]
            assert all(row["owner"] == self.user.email for row in body["results"])
            assert bool(body["next"]) == (offset == 0)

            statements = [query["sql"] for query in captured.captured_queries]
            scans = [
                sql for sql in statements if '"data_quality_dataqualitycheck"."config"' in sql and " LIMIT " not in sql
            ]
            assert len(scans) == 1, scans
            assert '"data_quality_dataqualitycheck"."metric_id" IN (' in scans[0]
            assert '"posthog_user"' not in scans[0]
            assert '"data_quality_dataqualitycheck"."description"' not in scans[0]
            metric_definition_reads = [
                sql
                for sql in statements
                if '"data_catalog_metric"."definition"' in sql and '"data_catalog_metric"."id" IN (' in sql
            ]
            assert 1 <= len(metric_definition_reads) <= 2, metric_definition_reads
            run_lookups = [
                sql for sql in statements if '"data_quality_dataqualitycheckrun"."quality_check_id" IN (' in sql
            ]
            assert run_lookups
            assert all(
                sum(identifier in sql for identifier in visible_ids) <= visibility_batch_size for sql in run_lookups
            ), run_lookups

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

    def test_the_overview_fails_closed_when_a_relationship_target_was_deleted(self) -> None:
        self._check(
            self.customers,
            check_type=CheckType.RELATIONSHIPS,
            column_name="customer_id",
            config={
                "to_subject_type": SubjectType.VIEW,
                "to_subject_uuid": str(self.orders.id),
                "to_column": "id",
            },
        )
        self.orders.delete()
        self._deny(self._make_view("secrets"))

        listed = self.client.get(self.checks_url)

        assert listed.json()["results"] == []

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
        api.record_check_run(
            self.team.id,
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
        # More metrics than the page checks, so the catalog's size cannot reach the result.
        metrics = [self._metric(f"metric_{index}") for index in range(5)]
        metric_checks = [
            self._check(
                self.orders,
                subject_type=SubjectType.METRIC,
                saved_query_id=None,
                metric_id=metric.id,
                subject_name=metric.name,
                check_type=CheckType.CUSTOM_SQL,
                column_name="",
                config={"query": "SELECT * FROM {metric} WHERE value < 1"},
            )
            for metric in metrics[:2]
        ]

        with self.assertNumQueries(4):
            located = api.subject_locations(self.team.id, [*views, *tables, *metric_checks])

        assert len(located) == 7

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
