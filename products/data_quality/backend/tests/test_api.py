from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.constants import AvailableFeature

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType
from products.data_quality.backend.logic import checks as checks_logic
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.data_quality.backend.presentation.serializers import DataQualitySuiteRunSerializer
from products.data_quality.backend.presentation.views import SavedQueryCheckViewSet
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable

from ee.models.rbac.access_control import AccessControl

START_SUITE = "products.data_quality.backend.logic.checks.sync_connect"
FLAG = "products.data_quality.backend.presentation.views.is_data_quality_checks_enabled"


class TestCheckViewSetScopes(SimpleTestCase):
    @parameterized.expand(
        [
            ("query_gated_read", "list", "GET", ["warehouse_view:read", "query:read"]),
            ("query_gated_write", "create", "POST", ["warehouse_view:write", "query:read"]),
            ("inherited_access_control", "users_with_access", "GET", ["access_control:read"]),
        ]
    )
    def test_required_scopes_per_action(self, _name: str, action: str, method: str, expected: list[str]) -> None:
        # The query gate is this viewset's own scope rule; everything else has to keep deferring, or the
        # access-control actions it inherits would answer to a warehouse token with no access_control scope.
        view = SavedQueryCheckViewSet()
        view.action = action

        assert view.dangerously_get_required_scopes(APIRequestFactory().generic(method, "/"), view) == expected


class TestDataQualityCheckAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1 AS customer_id"}
        )
        self.url = self._checks_url(self.view.id)
        flag = patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _checks_url(self, saved_query_id) -> str:
        return f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_id}/checks"

    def _suite_runs_url(self) -> str:
        return f"/api/projects/{self.team.id}/warehouse_saved_queries/{self.view.id}/check_suite_runs"

    def _gate_url(self) -> str:
        return f"/api/projects/{self.team.id}/data_warehouse/data_quality_gate/"

    def _table_checks_url(self) -> str:
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="_key", access_secret="_secret")
        table = DataWarehouseTable.objects.create(
            name="orders_source",
            team=self.team,
            columns={"customer_id": "String"},
            credential=credential,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="http://localhost:19000/bucket/orders_source",
        )
        return f"/api/projects/{self.team.id}/warehouse_tables/{table.id}/checks"

    def _payload(self, **overrides) -> dict:
        return {
            "check_type": CheckType.NOT_NULL,
            "column_name": "customer_id",
            **overrides,
        }

    def _create_check(self, **overrides) -> DataQualityCheck:
        response = self.client.post(f"{self.url}/", self._payload(**overrides))
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return DataQualityCheck.objects.for_team(self.team.id).get(id=response.json()["id"])

    def _make_view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

    def test_the_whole_surface_is_gated_on_the_feature_flag(self) -> None:
        with patch(FLAG, return_value=False):
            assert self.client.get(f"{self.url}/").status_code == status.HTTP_403_FORBIDDEN
            assert self.client.post(f"{self.url}/", self._payload()).status_code == status.HTTP_403_FORBIDDEN
            assert self.client.get(f"{self.url}/check_types/").status_code == status.HTTP_403_FORBIDDEN
            assert self.client.get(self._gate_url()).status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("view",), ("table",)])
    def test_create_returns_the_fingerprint_and_re_creating_upserts(self, kind: str) -> None:
        url = self.url if kind == "view" else self._table_checks_url()
        created = self.client.post(f"{url}/", self._payload())
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        assert created.json()["fingerprint"]

        again = self.client.post(f"{url}/", self._payload(description="clarified"))

        assert again.status_code == status.HTTP_200_OK
        assert again.json()["id"] == created.json()["id"]
        assert again.json()["description"] == "clarified"
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("unknown_check_type", {"check_type": "anomaly"}),
            ("config_key_not_in_schema", {"config": {"tolerance": 3}}),
            ("column_required_but_missing", {"column_name": ""}),
            (
                "accepted_values_needs_values",
                {"check_type": CheckType.ACCEPTED_VALUES, "config": {"values": []}},
            ),
        ]
    )
    def test_invalid_definitions_are_rejected(self, _name, overrides: dict) -> None:
        response = self.client.post(f"{self.url}/", self._payload(**overrides))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 0

    def test_creating_under_an_unknown_parent_is_rejected(self) -> None:
        response = self.client.post(f"{self._checks_url(uuid4())}/", self._payload())

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 0

    def test_a_name_cannot_be_reused_within_a_project(self) -> None:
        self._create_check(name="orders_customer_id_not_null")

        clash = self.client.post(
            f"{self.url}/",
            self._payload(column_name="total", name="orders_customer_id_not_null"),
        )

        assert clash.status_code == status.HTTP_409_CONFLICT

    def test_a_differently_typed_config_upserts_instead_of_duplicating(self) -> None:
        # The fingerprint hashes config after its type model parses it, so an agent that sends
        # max_age_minutes as a string matches the check it already created with an int.
        first = self.client.post(
            f"{self.url}/",
            self._payload(check_type=CheckType.FRESHNESS, column_name="created_at", config={"max_age_minutes": 60}),
        )
        assert first.status_code == status.HTTP_201_CREATED

        again = self.client.post(
            f"{self.url}/",
            self._payload(check_type=CheckType.FRESHNESS, column_name="created_at", config={"max_age_minutes": "60"}),
        )

        assert again.status_code == status.HTTP_200_OK
        assert again.json()["id"] == first.json()["id"]
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 1

    def test_re_creating_a_named_check_upserts_rather_than_conflicting(self) -> None:
        # The name belongs to the same check, so an identical re-propose must upsert, not 409.
        created = self.client.post(f"{self.url}/", self._payload(name="orders_customer_id_not_null"))
        assert created.status_code == status.HTTP_201_CREATED

        again = self.client.post(f"{self.url}/", self._payload(name="orders_customer_id_not_null"))

        assert again.status_code == status.HTTP_200_OK
        assert again.json()["id"] == created.json()["id"]

    @parameterized.expand([("check_type",), ("column_name",), ("config",)])
    def test_the_assertion_cannot_be_edited_in_place(self, field: str) -> None:
        # Editing it would leave the fingerprint describing a different check, so later identical
        # creates would duplicate instead of upserting.
        check = self._create_check()
        new_value = {
            "check_type": CheckType.UNIQUE,
            "column_name": "total",
            "config": {"values": ["a"]},
        }[field]

        response = self.client.patch(f"{self.url}/{check.id}/", {field: new_value})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        check.refresh_from_db()
        assert str(getattr(check, field)) != str(new_value)

    def test_a_racing_identical_create_returns_the_winning_row_not_a_500(self) -> None:
        # Two identical creates can both miss the fingerprint lookup and race to insert; the uniqueness
        # constraint lets only one win. Simulate the loser by making its lookup miss the row the winner
        # already committed: it must catch the IntegrityError, refetch, and return the winner with 200.
        winner = self._create_check()

        with patch.object(checks_logic, "_find_by_fingerprint", side_effect=[None, winner]):
            response = self.client.post(f"{self.url}/", self._payload(description="racing"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == str(winner.id)
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 1

    @parameterized.expand([("unscoped", "", None), ("single_view", SubjectType.VIEW, "view")])
    def test_suite_run_subject_type_is_null_when_not_scoped_to_one_subject(self, _name, stored, expected) -> None:
        # A manual check-id or multi-subject run stores a blank subject_type, but the response schema
        # only permits table/view -- surface the unscoped case as null, never a blank string.
        suite_run = DataQualitySuiteRun(team=self.team, trigger="manual", subject_type=stored)

        assert DataQualitySuiteRunSerializer(suite_run).data["subject_type"] == expected

    @parameterized.expand([("not_a_list", {"label": 1}), ("non_string_element", [{"nested": 1}])])
    def test_tags_must_be_a_list_of_strings(self, _name, tags) -> None:
        # The model field is untyped JSON; the serializer pins it to a list of strings so the generated
        # client and Zod schema are typed rather than accepting arbitrary JSON.
        response = self.client.post(f"{self.url}/", self._payload(tags=tags))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 0

    def test_a_workflow_that_cannot_start_does_not_strand_a_running_suite(self) -> None:
        check = self._create_check()

        with patch(START_SUITE, side_effect=RuntimeError("temporal down")):
            response = self.client.post(f"{self.url}/{check.id}/run/")

        assert response.status_code >= 500
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).latest("created_at")
        assert suite_run.status == "failed"
        assert suite_run.finished_at is not None

    def test_soft_delete_hides_the_check_but_keeps_it_readable_by_id(self) -> None:
        check = self._create_check()

        assert self.client.delete(f"{self.url}/{check.id}/").status_code == status.HTTP_204_NO_CONTENT

        assert self.client.get(f"{self.url}/").json()["results"] == []
        check.refresh_from_db()
        assert check.deleted is True
        assert check.enabled is False

    def test_list_is_scoped_to_the_parent_and_filters_by_check_type(self) -> None:
        self._create_check()
        self._create_check(check_type=CheckType.UNIQUE)
        other_view = self._make_view("refunds")
        other = self.client.post(f"{self._checks_url(other_view.id)}/", self._payload())
        assert other.status_code == status.HTTP_201_CREATED

        listed = self.client.get(f"{self.url}/")
        filtered = self.client.get(f"{self.url}/?check_type={CheckType.UNIQUE}")

        assert {row["subject_uuid"] for row in listed.json()["results"]} == {str(self.view.id)}
        assert len(listed.json()["results"]) == 2
        assert [row["check_type"] for row in filtered.json()["results"]] == [CheckType.UNIQUE]

    def test_check_types_exposes_a_config_schema_per_type(self) -> None:
        response = self.client.get(f"{self.url}/check_types/")

        assert response.status_code == status.HTTP_200_OK
        by_type = {row["check_type"]: row for row in response.json()}
        assert set(by_type) == {t.value for t in CheckType}
        assert by_type["accepted_values"]["config_schema"]["required"] == ["values"]
        assert by_type["row_count"]["requires_column"] is False

    @parameterized.expand(
        [
            ("no_checks", [], "unknown"),
            ("all_passing", [(CheckSeverity.ERROR, CheckRunStatus.PASSED)], "healthy"),
            (
                "error_severity_failure",
                [(CheckSeverity.ERROR, CheckRunStatus.FAILED), (CheckSeverity.WARN, CheckRunStatus.PASSED)],
                "failing",
            ),
            (
                "warn_only_failure",
                [(CheckSeverity.WARN, CheckRunStatus.FAILED), (CheckSeverity.ERROR, CheckRunStatus.PASSED)],
                "warn",
            ),
            (
                "execution_error_outranks_a_warning",
                [(CheckSeverity.WARN, CheckRunStatus.FAILED), (CheckSeverity.ERROR, CheckRunStatus.ERRORED)],
                "erroring",
            ),
        ]
    )
    def test_health_rolls_up_the_worst_outcome(self, _name, states: list[tuple], expected: str) -> None:
        for index, (severity, last_status) in enumerate(states):
            DataQualityCheck.objects.for_team(self.team.id).create(
                team=self.team,
                subject_type=SubjectType.VIEW,
                saved_query_id=self.view.id,
                subject_name="orders",
                check_type=CheckType.NOT_NULL,
                column_name=f"col_{index}",
                fingerprint=uuid4().hex,
                severity=severity,
                last_status=last_status,
            )

        response = self.client.get(f"{self.url}/health/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["health"] == expected
        assert response.json()["checks_total"] == len(states)

    def test_health_ignores_disabled_checks(self) -> None:
        # A disabled failing check must not drive the verdict, or health would read 'failing' while
        # checks_failing counts 0 -- the verdict and the counts have to agree.
        common = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "saved_query_id": self.view.id,
            "subject_name": "orders",
            "check_type": CheckType.NOT_NULL,
            "severity": CheckSeverity.ERROR,
        }
        DataQualityCheck.objects.for_team(self.team.id).create(
            column_name="enabled_col", fingerprint=uuid4().hex, last_status=CheckRunStatus.PASSED, **common
        )
        DataQualityCheck.objects.for_team(self.team.id).create(
            column_name="disabled_col",
            fingerprint=uuid4().hex,
            last_status=CheckRunStatus.FAILED,
            enabled=False,
            **common,
        )

        response = self.client.get(f"{self.url}/health/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["health"] == "healthy"
        assert response.json()["checks_total"] == 1
        assert response.json()["checks_failing"] == 0

    def test_run_returns_a_pollable_suite_run(self) -> None:
        check = self._create_check()

        with patch(START_SUITE, return_value=MagicMock(start_workflow=AsyncMock())):
            response = self.client.post(f"{self.url}/{check.id}/run/")

        assert response.status_code == status.HTTP_200_OK
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).get(id=response.json()["id"])
        assert suite_run.status == "running"
        assert response.json()["workflow_id"] == suite_run.workflow_id
        # The handle is only pollable if it carries the subject: the nested routes filter on it.
        polled = self.client.get(f"{self._suite_runs_url()}/{suite_run.id}/")
        assert polled.status_code == status.HTTP_200_OK
        listed = self.client.get(f"{self._suite_runs_url()}/")
        assert str(suite_run.id) in {row["id"] for row in listed.json()["results"]}

    def test_run_all_records_the_subject_on_the_report(self) -> None:
        self._create_check()

        with patch(START_SUITE, return_value=MagicMock(start_workflow=AsyncMock())):
            response = self.client.post(f"{self.url}/run_all/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["subject_uuid"] == str(self.view.id)

    def test_suite_runs_list_the_parents_single_subject_suites(self) -> None:
        # Multi-subject sweep suites carry no parent, so this surface must not serve them -- they
        # stay reachable through information_schema, the cross-subject surface.
        mine = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=self.view.id
        )
        sweep = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            suite_run=mine,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.view.id,
            subject_name="orders",
            check_type=CheckType.NOT_NULL,
            check_fingerprint=uuid4().hex,
            status=CheckRunStatus.FAILED,
            failed_row_count=3,
        )

        base = self._suite_runs_url()
        listed = self.client.get(f"{base}/")

        assert {row["id"] for row in listed.json()["results"]} == {str(mine.id)}
        assert self.client.get(f"{base}/{sweep.id}/").status_code == status.HTTP_404_NOT_FOUND
        check_runs = self.client.get(f"{base}/{mine.id}/check_runs/")
        assert [row["subject_name"] for row in check_runs.json()] == ["orders"]

    def _deny_the_view(self) -> None:
        # Deny the default member object-level access to the "orders" view, the way the HogQL
        # database sees it -- so denied_subject_names() picks it up and the endpoint hides it.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(self.view.id),
            organization_member=self.organization_membership,
            access_level="none",
        )
        # Warehouse table/view denial only flows into the HogQL database behind this flag.
        warehouse_ac = patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda name, *a, **k: name == "hogql-warehouse-access-control",
        )
        warehouse_ac.start()
        self.addCleanup(warehouse_ac.stop)
        cache.clear()

    @parameterized.expand(
        [
            ("list", lambda self, check, suite: self.client.get(f"{self.url}/")),
            ("retrieve", lambda self, check, suite: self.client.get(f"{self.url}/{check.id}/")),
            ("create", lambda self, check, suite: self.client.post(f"{self.url}/", self._payload())),
            ("run", lambda self, check, suite: self.client.post(f"{self.url}/{check.id}/run/")),
            ("runs", lambda self, check, suite: self.client.get(f"{self.url}/{check.id}/runs/")),
            ("run_all", lambda self, check, suite: self.client.post(f"{self.url}/run_all/")),
            ("health", lambda self, check, suite: self.client.get(f"{self.url}/health/")),
            ("suite_runs_list", lambda self, check, suite: self.client.get(f"{self._suite_runs_url()}/")),
            (
                "suite_run_check_runs",
                lambda self, check, suite: self.client.get(f"{self._suite_runs_url()}/{suite.id}/check_runs/"),
            ),
        ]
    )
    def test_a_denied_parent_subject_blocks_every_action(self, _name: str, call) -> None:
        # Authoring, running, or reading anything under a table the member cannot query would leak
        # its shape and observed counts. The subject is the parent in the URL, so every action 403s.
        check = self._create_check()
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=self.view.id
        )
        self._deny_the_view()

        assert call(self, check, suite).status_code == status.HTTP_403_FORBIDDEN

    def test_deleting_a_denied_subject_does_not_hand_its_history_over(self) -> None:
        # An orphan resolves to an empty name, which matches no denial, so deleting the view would
        # otherwise lift the member's denial along with it.
        self._create_check()
        self._deny_the_view()
        self.view.delete()

        assert self.client.get(f"{self.url}/").status_code == status.HTTP_403_FORBIDDEN

    def test_an_unrestricted_member_still_reads_an_orphaned_subjects_checks(self) -> None:
        # Orphaned history stays reachable: checks on a deleted subject are skipped, not hidden.
        self._create_check()
        self.view.delete()

        assert self.client.get(f"{self.url}/").status_code == status.HTTP_200_OK

    @parameterized.expand(
        [
            ("custom_sql", CheckType.CUSTOM_SQL, "", {"query": "SELECT 1 FROM orders"}),
            ("relationships", CheckType.RELATIONSHIPS, "customer_id", None),
        ]
    )
    def test_a_denied_referenced_subject_blocks_authoring(self, _name, check_type, column_name, config) -> None:
        # The parent is not the only subject a check reads: custom_sql selects arbitrary tables
        # and relationships names a second subject. Authoring one that reads the denied "orders" from an
        # allowed subject must 403 -- the worker runs it with team scope only, a count oracle otherwise.
        allowed = self._make_view("customers")
        if config is None:
            config = {"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(self.view.id), "to_column": "id"}
        self._deny_the_view()

        response = self.client.post(
            f"{self._checks_url(allowed.id)}/",
            self._payload(check_type=check_type, column_name=column_name, config=config),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 0

    @parameterized.expand(
        [
            ("run", lambda self, url, check: self.client.post(f"{url}/{check.id}/run/")),
            ("run_all", lambda self, url, check: self.client.post(f"{url}/run_all/")),
            ("runs", lambda self, url, check: self.client.get(f"{url}/{check.id}/runs/")),
        ]
    )
    def test_a_denied_referenced_subject_blocks_triggering_and_reading_history(self, _name, call) -> None:
        # The parent subject stays allowed, so the check is visible -- but its custom_sql reads the
        # denied "orders". Triggering it (run, run_all) and reading its run history (runs, which
        # exposes counts from past executions) gate on every subject it references, not just the parent.
        allowed = self._make_view("customers")
        check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            config={"query": "SELECT 1 FROM orders"},
            fingerprint=uuid4().hex,
        )
        self._deny_the_view()

        assert call(self, self._checks_url(allowed.id), check).status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("create", lambda self, check: self.client.post(f"{self.url}/", self._payload(column_name="total"))),
            ("run", lambda self, check: self.client.post(f"{self.url}/{check.id}/run/")),
            ("run_all", lambda self, check: self.client.post(f"{self.url}/run_all/")),
            ("runs", lambda self, check: self.client.get(f"{self.url}/{check.id}/runs/")),
            ("list", lambda self, check: self.client.get(f"{self.url}/")),
            ("retrieve", lambda self, check: self.client.get(f"{self.url}/{check.id}/")),
            ("health", lambda self, check: self.client.get(f"{self.url}/health/")),
            ("suite_runs_list", lambda self, check: self.client.get(f"{self._suite_runs_url()}/")),
        ]
    )
    def test_query_denied_members_cannot_author_execute_or_read_check_outcomes(self, _name: str, call) -> None:
        # A check executes HogQL and its result columns are a count oracle over warehouse rows, and
        # reading a check back or its health rollup exposes the same counts one step removed, so
        # warehouse access alone must not be enough for any of them.
        check = self._create_check()
        AccessControl.objects.create(team=self.team, resource="query", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()

        assert call(self, check).status_code == status.HTTP_403_FORBIDDEN

    def test_check_types_catalog_stays_readable_without_query_access(self) -> None:
        # The check-type catalog is static schema metadata with no execution state, so unlike the
        # check rows it is not gated on query access -- an agent must be able to discover config shapes.
        AccessControl.objects.create(team=self.team, resource="query", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()

        assert self.client.get(f"{self.url}/check_types/").status_code == status.HTTP_200_OK

    def test_another_projects_checks_are_not_visible(self) -> None:
        check = self._create_check()
        other_team = self.create_team_with_organization(self.organization)

        response = self.client.get(
            f"/api/projects/{other_team.id}/warehouse_saved_queries/{self.view.id}/checks/{check.id}/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_the_materialization_gate_round_trips(self) -> None:
        url = self._gate_url()

        assert self.client.get(url).json() == {"gate_materialization_on_checks": False}

        patched = self.client.patch(url, {"gate_materialization_on_checks": True})

        assert patched.status_code == status.HTTP_200_OK
        assert patched.json() == {"gate_materialization_on_checks": True}
        assert self.client.get(url).json() == {"gate_materialization_on_checks": True}

    def test_writing_the_team_wide_gate_needs_resource_level_editor_access(self) -> None:
        # The gate is a project-wide setting, so an object-level editor grant on a single view must
        # not be enough to flip it -- writing needs resource-level warehouse editor access. Reading
        # stays open to a warehouse viewer.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="viewer")
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(self.view.id),
            organization_member=self.organization_membership,
            access_level="editor",
        )
        url = self._gate_url()

        assert self.client.get(url).status_code == status.HTTP_200_OK
        assert self.client.patch(url, {"gate_materialization_on_checks": True}).status_code == status.HTTP_403_FORBIDDEN
