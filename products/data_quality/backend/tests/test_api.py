from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.constants import AvailableFeature

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade import api
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType
from products.data_quality.backend.logic import checks as checks_logic
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.data_quality.backend.presentation.serializers import DataQualitySuiteRunSerializer
from products.data_quality.backend.presentation.views import SavedQueryCheckViewSet
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable

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

    def _suite_runs_url(self, saved_query_id=None) -> str:
        parent = saved_query_id or self.view.id
        return f"/api/projects/{self.team.id}/warehouse_saved_queries/{parent}/check_suite_runs"

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

    def _create_check(self, url: str | None = None, **overrides) -> DataQualityCheck:
        response = self.client.post(f"{url or self.url}/", self._payload(**overrides))
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return DataQualityCheck.objects.for_team(self.team.id).get(id=response.json()["id"])

    def _make_view(self, name: str) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team, name=name, query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )

    def _pinned(self, *views: DataWarehouseSavedQuery) -> list[dict[str, str]]:
        return [{"subject_type": str(SubjectType.VIEW), "subject_uuid": str(view.id)} for view in views]

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

    @parameterized.expand(
        [
            ("view", "type", {"check_type": CheckType.UNIQUE}),
            ("view", "column", {"column_name": "total"}),
            (
                "view",
                "config",
                {"check_type": CheckType.ACCEPTED_VALUES, "config": {"values": ["paid", "refunded"]}},
            ),
            (
                "view",
                "custom_sql",
                {"check_type": CheckType.CUSTOM_SQL, "column_name": "", "config": {"query": "SELECT 1"}},
            ),
            ("table", "type", {"check_type": CheckType.UNIQUE}),
            ("table", "config", {"check_type": CheckType.ROW_COUNT, "column_name": "", "config": {"min": 1}}),
        ]
    )
    def test_editing_the_assertion_keeps_the_check_identity(self, kind: str, _case: str, edit: dict) -> None:
        url = self.url if kind == "view" else self._table_checks_url()
        check = self._create_check(url=url)
        ran_at = now()
        DataQualityCheck.objects.for_team(self.team.id).filter(id=check.id).update(
            last_status=CheckRunStatus.FAILED, last_run_at=ran_at
        )

        response = self.client.patch(f"{url}/{check.id}/", edit)

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["id"] == str(check.id)
        assert body["last_status"] == CheckRunStatus.FAILED
        assert body["last_run_at"] is not None
        assert body["fingerprint"] != check.fingerprint
        check.refresh_from_db()
        assert check.check_type == edit.get("check_type", check.check_type)
        assert check.column_name == edit.get("column_name", check.column_name)
        assert edit.get("config", {}).items() <= check.config.items()
        assert check.created_by == self.user
        assert check.last_run_at == ran_at

    def test_a_metadata_edit_leaves_the_definition_and_its_author_alone(self) -> None:
        check = self._create_check()

        response = self.client.patch(f"{self.url}/{check.id}/", {"description": "why this matters", "tags": ["core"]})

        assert response.status_code == status.HTTP_200_OK, response.json()
        check.refresh_from_db()
        assert check.description == "why this matters"
        assert check.fingerprint == response.json()["fingerprint"]
        assert check.definition_author is None

    def test_editing_the_assertion_records_who_authorized_it(self) -> None:
        # Automated runs of a check that reads beyond its subject execute as this user, so it has to
        # be whoever last changed what the check reads, not whoever created it.
        check = self._create_check()

        self.client.patch(f"{self.url}/{check.id}/", {"check_type": CheckType.UNIQUE})

        check.refresh_from_db()
        assert check.definition_author == self.user

    def test_editing_into_another_active_definition_writes_nothing(self) -> None:
        taken = self._create_check(check_type=CheckType.UNIQUE, name="orders_customer_id_unique")
        check = self._create_check(column_name="total")

        response = self.client.patch(
            f"{self.url}/{check.id}/",
            {"check_type": CheckType.UNIQUE, "column_name": "customer_id", "description": "not saved either"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "duplicate_definition"
        check.refresh_from_db()
        assert check.column_name == "total"
        assert check.description == ""
        assert taken.fingerprint != check.fingerprint

    def test_editing_onto_a_taken_name_is_a_field_error(self) -> None:
        self._create_check(check_type=CheckType.UNIQUE, name="orders_customer_id_unique")
        check = self._create_check(column_name="total")

        response = self.client.patch(f"{self.url}/{check.id}/", {"name": "orders_customer_id_unique"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        check.refresh_from_db()
        assert check.name == ""

    def test_a_definition_freed_by_deletion_becomes_a_new_check(self) -> None:
        # The old check keeps its own id and history; reusing the definition must not resurrect it.
        first = self._create_check()
        assert self.client.delete(f"{self.url}/{first.id}/").status_code == status.HTTP_204_NO_CONTENT

        again = self.client.post(f"{self.url}/", self._payload())

        assert again.status_code == status.HTTP_201_CREATED, again.json()
        assert again.json()["id"] != str(first.id)
        first.refresh_from_db()
        assert first.deleted is True

    def test_a_name_freed_by_deletion_can_be_used_again(self) -> None:
        # A deleted check keeps its name as history. Holding it against a new check would make the
        # delete irreversible for anyone who wants that name back.
        first = self._create_check(name="orders_customer_id_not_null")
        assert self.client.delete(f"{self.url}/{first.id}/").status_code == status.HTTP_204_NO_CONTENT

        again = self.client.post(f"{self.url}/", self._payload(column_name="total", name="orders_customer_id_not_null"))

        assert again.status_code == status.HTTP_201_CREATED, again.json()
        assert again.json()["id"] != str(first.id)

    def test_a_definition_race_lost_to_the_constraint_reads_as_a_conflict(self) -> None:
        # Two rows can both clear the duplicate precheck and race to commit one fingerprint; the
        # active-only constraint settles it, and the loser must see the same field error the
        # precheck raises rather than a 500.
        winner = self._create_check(check_type=CheckType.UNIQUE)
        loser = self._create_check(column_name="total")

        with patch.object(checks_logic, "_ensure_definition_available", return_value=None):
            response = self.client.patch(
                f"{self.url}/{loser.id}/", {"check_type": CheckType.UNIQUE, "column_name": "customer_id"}
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["code"] == "duplicate_definition"
        loser.refresh_from_db()
        assert loser.column_name == "total"
        assert winner.check_type == CheckType.UNIQUE

    def test_a_name_race_lost_to_the_constraint_reads_as_a_conflict(self) -> None:
        # Two rows can both clear the name precheck and race to commit one name; the constraint
        # settles it, and the loser must see the same field error the precheck raises, not a 500.
        self._create_check(check_type=CheckType.UNIQUE, name="orders_customer_id_unique")
        loser = self._create_check(column_name="total")

        with patch.object(checks_logic, "_name_taken", side_effect=[False, True]):
            response = self.client.patch(f"{self.url}/{loser.id}/", {"name": "orders_customer_id_unique"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "name"
        loser.refresh_from_db()
        assert loser.name == ""

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

    def test_listing_a_subjects_checks_leaves_out_the_ones_reading_a_denied_subject(self) -> None:
        # The parent gate cleared "customers", but a check under it names the denied "orders" in its
        # config, which the routes that address one check already refuse to serve.
        allowed = self._make_view("customers")
        DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            config={"query": "SELECT 1 FROM orders"},
            fingerprint=uuid4().hex,
        )
        self._deny_the_view()

        listed = self.client.get(f"{self._checks_url(allowed.id)}/")

        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert listed.json()["results"] == []

    def test_a_subjects_health_leaves_out_the_checks_reading_a_denied_subject(self) -> None:
        # The rollup counts the same checks the list serves, so one the list withholds must not be
        # counted back in here: checks_failing answers the same question one step removed.
        allowed = self._make_view("customers")
        DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            config={"query": "SELECT 1 FROM orders"},
            fingerprint=uuid4().hex,
            last_status=CheckRunStatus.FAILED,
        )
        self._deny_the_view()

        health = self.client.get(f"{self._checks_url(allowed.id)}/health/")

        assert health.status_code == status.HTTP_200_OK, health.json()
        assert health.json()["checks_total"] == 0
        assert health.json()["checks_failing"] == 0
        assert health.json()["health"] == "unknown"

    @parameterized.expand([("pinned", True), ("recorded before pinning", False)])
    def test_editing_a_check_does_not_unlock_the_history_it_used_to_read(self, _name: str, pinned: bool) -> None:
        # Authorizing history against the definition the check carries *now* lets a member point a
        # check that reads the denied "orders" at something harmless and then read what it recorded:
        # the compiled query, the failed-row count and the observed value. A run that pinned no
        # references is judged by its type rather than by the edited check.
        allowed = self._make_view("customers")
        reads_orders = {"query": "SELECT 1 FROM orders"}
        check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            config=reads_orders,
            fingerprint=uuid4().hex,
        )
        api.record_check_run(
            self.team.id,
            suite_run=DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual"),
            quality_check=check,
            subject_type=SubjectType.VIEW,
            subject_uuid=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            check_config=reads_orders,
            referenced_subjects=self._pinned(self.view) if pinned else None,
            check_fingerprint=check.fingerprint,
            status=CheckRunStatus.FAILED,
            failed_row_count=3,
            compiled_query="SELECT * FROM orders",
        )
        self._deny_the_view()

        url = f"{self._checks_url(allowed.id)}/{check.id}"
        edited = self.client.patch(url + "/", {"check_type": CheckType.NOT_NULL, "column_name": "id", "config": {}})
        history = self.client.get(f"{url}/runs/")

        assert edited.status_code == status.HTTP_200_OK, edited.json()
        assert history.status_code == status.HTTP_200_OK
        assert history.json() == []

    def test_accepted_values_are_stored_as_the_column_holds_them(self) -> None:
        # The editor can only send strings. Whether the coercion is wired into the create path at all
        # is what this covers; the type matrix itself is unit-tested against the spec.
        view = self._make_view("payments")
        DataWarehouseSavedQuery.objects.filter(id=view.id).update(columns={"amount": "Nullable(Int64)"})

        response = self.client.post(
            f"{self._checks_url(view.id)}/",
            {"check_type": CheckType.ACCEPTED_VALUES, "column_name": "amount", "config": {"values": ["1", "2"]}},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        check = DataQualityCheck.objects.for_team(self.team.id).get(id=response.json()["id"])
        assert check.config["values"] == [1.0, 2.0]

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
            (
                "partial_update",
                lambda self, check, suite: self.client.patch(f"{self.url}/{check.id}/", {"description": "edited"}),
            ),
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

    def test_editing_a_check_to_read_a_denied_subject_writes_nothing(self) -> None:
        # The stored definition cleared the denial; the candidate one has to clear it too, or an edit
        # is the way to point a visible check at a table the member cannot read.
        allowed = self._make_view("customers")
        check = self._create_check(url=self._checks_url(allowed.id), column_name="id")
        self._deny_the_view()

        response = self.client.patch(
            f"{self._checks_url(allowed.id)}/{check.id}/",
            {"check_type": CheckType.CUSTOM_SQL, "column_name": "", "config": {"query": "SELECT 1 FROM orders"}},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        check.refresh_from_db()
        assert check.check_type == CheckType.NOT_NULL

    def _suite_with_two_runs(self, allowed: DataWarehouseSavedQuery) -> DataQualitySuiteRun:
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=allowed.id
        )
        for check_type, config, name, referenced in (
            (CheckType.NOT_NULL, {}, "reads_only_the_parent", []),
            (CheckType.CUSTOM_SQL, {"query": "SELECT 1 FROM orders"}, "reads_the_denied_view", self._pinned(self.view)),
        ):
            check = DataQualityCheck.objects.for_team(self.team.id).create(
                team=self.team,
                name=name,
                subject_type=SubjectType.VIEW,
                saved_query_id=allowed.id,
                subject_name="customers",
                check_type=check_type,
                column_name="total" if check_type == CheckType.NOT_NULL else "",
                config=config,
                fingerprint=uuid4().hex,
            )
            api.record_check_run(
                self.team.id,
                suite_run=suite,
                quality_check=check,
                subject_type=SubjectType.VIEW,
                subject_uuid=allowed.id,
                subject_name="customers",
                check_type=check_type,
                check_config=config,
                referenced_subjects=referenced,
                check_fingerprint=check.fingerprint,
                status=CheckRunStatus.FAILED,
                failed_row_count=3,
                compiled_query="SELECT * FROM orders",
            )
        return suite

    @parameterized.expand(
        [
            ("denied_member", True, [CheckType.NOT_NULL]),
            ("allowed_member", False, [CheckType.CUSTOM_SQL, CheckType.NOT_NULL]),
        ]
    )
    def test_suite_check_runs_withhold_a_run_that_read_a_denied_subject(
        self, _name: str, deny: bool, expected_types: list[str]
    ) -> None:
        # A run carries its compiled query, failed-row count and observed value. A check on an allowed
        # parent whose custom_sql reads the denied "orders" would disclose all three here, which is
        # what the check-level routes refuse. The rest of the suite stays readable.
        allowed = self._make_view("customers")
        suite = self._suite_with_two_runs(allowed)
        if deny:
            self._deny_the_view()

        response = self.client.get(f"{self._suite_runs_url(allowed.id)}/{suite.id}/check_runs/")

        assert response.status_code == status.HTTP_200_OK
        assert sorted(row["check_type"] for row in response.json()) == sorted(expected_types)

    def test_a_suite_whose_run_read_a_denied_subject_is_withheld(self) -> None:
        # The suite row carries passed/failed/errored/skipped over every check it ran, while
        # check_runs hands back only the readable ones. Serving both names the withheld check's
        # outcome by subtraction, so the row with the counters is the one to hold back.
        allowed = self._make_view("customers")
        suite = self._suite_with_two_runs(allowed)
        self._deny_the_view()

        base = self._suite_runs_url(allowed.id)
        listed = self.client.get(f"{base}/")
        retrieved = self.client.get(f"{base}/{suite.id}/")

        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert listed.json()["results"] == []
        assert retrieved.status_code == status.HTTP_404_NOT_FOUND

    def test_a_run_whose_definition_is_unknown_is_judged_by_its_type(self) -> None:
        # Predating the pinned references, so there is nothing recorded to judge. A type that cannot
        # reach past its own subject read only the parent this surface already authorized; one that
        # can is withheld, since the current definition is not evidence of what the run executed.
        allowed = self._make_view("customers")
        suite = self._suite_with_two_runs(allowed)
        DataQualityCheckRun.objects.for_team(self.team.id).filter(suite_run=suite).update(
            check_config=None, referenced_subjects=None, quality_check=None
        )
        self._deny_the_view()

        response = self.client.get(f"{self._suite_runs_url(allowed.id)}/{suite.id}/check_runs/")

        assert response.status_code == status.HTTP_200_OK
        assert [row["check_type"] for row in response.json()] == [CheckType.NOT_NULL]

    @parameterized.expand([("relationships",), ("custom_sql",)])
    def test_deleting_a_referenced_subject_does_not_hand_its_history_over(self, check_type: str) -> None:
        # Deletion takes the denial with it: the denial set is rebuilt from the objects that still
        # exist, so a deleted subject stops looking denied. The run pinned what it read, and an
        # identity that no longer resolves is no proof the caller was allowed it.
        allowed = self._make_view("customers")
        config: dict = (
            {"query": "SELECT 1 FROM orders"}
            if check_type == CheckType.CUSTOM_SQL
            else {"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(self.view.id), "to_column": "id"}
        )
        check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=allowed.id,
            subject_name="customers",
            check_type=check_type,
            column_name="" if check_type == CheckType.CUSTOM_SQL else "customer_id",
            config=config,
            fingerprint=uuid4().hex,
        )
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=allowed.id
        )
        api.record_check_run(
            self.team.id,
            suite_run=suite,
            quality_check=check,
            subject_type=SubjectType.VIEW,
            subject_uuid=allowed.id,
            subject_name="customers",
            check_type=check_type,
            check_config=config,
            referenced_subjects=self._pinned(self.view),
            check_fingerprint=check.fingerprint,
            status=CheckRunStatus.FAILED,
            failed_row_count=3,
            compiled_query="SELECT * FROM orders",
        )
        self._deny_the_view()
        self.view.delete()

        suite_runs = self.client.get(f"{self._suite_runs_url(allowed.id)}/{suite.id}/check_runs/")
        history = self.client.get(f"{self._checks_url(allowed.id)}/{check.id}/runs/")

        # The suite route filters, since it serves runs from many checks. The per-check route refuses,
        # since the one definition it serves is the one that cannot be established.
        assert suite_runs.status_code == status.HTTP_200_OK
        assert suite_runs.json() == []
        assert history.status_code == status.HTTP_403_FORBIDDEN

    def test_reusing_a_deleted_subjects_name_does_not_hand_its_history_over(self) -> None:
        # Deleting a view frees its name, so a member can create their own "orders" and make the name
        # resolve for them again. Judged by name, the run that read the denied "orders" would then
        # read as harmless and hand over its compiled query and failed-row count.
        allowed = self._make_view("customers")
        reads_orders = {"query": "SELECT 1 FROM orders"}
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=allowed.id
        )
        api.record_check_run(
            self.team.id,
            suite_run=suite,
            subject_type=SubjectType.VIEW,
            subject_uuid=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            check_config=reads_orders,
            referenced_subjects=self._pinned(self.view),
            check_fingerprint=uuid4().hex,
            status=CheckRunStatus.FAILED,
            failed_row_count=3,
            compiled_query="SELECT * FROM orders",
        )
        self._deny_the_view()
        self.view.delete()
        self._make_view("orders")

        response = self.client.get(f"{self._suite_runs_url(allowed.id)}/{suite.id}/check_runs/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_a_run_that_read_an_allowed_subject_stays_visible_to_a_restricted_member(self) -> None:
        # Failing closed on identity must not swallow the history a restricted member may read: the
        # run pinned a view they are allowed, so being denied a different one changes nothing here.
        allowed = self._make_view("customers")
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=allowed.id
        )
        api.record_check_run(
            self.team.id,
            suite_run=suite,
            subject_type=SubjectType.VIEW,
            subject_uuid=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            check_config={"query": "SELECT 1 FROM customers"},
            referenced_subjects=self._pinned(allowed),
            check_fingerprint=uuid4().hex,
            status=CheckRunStatus.FAILED,
            failed_row_count=3,
        )
        self._deny_the_view()

        response = self.client.get(f"{self._suite_runs_url(allowed.id)}/{suite.id}/check_runs/")

        assert response.status_code == status.HTTP_200_OK
        assert [row["check_type"] for row in response.json()] == [CheckType.CUSTOM_SQL]

    def test_a_deleted_declared_subject_withholds_its_history_from_a_restricted_member(self) -> None:
        # Deleting a subject takes its denial with it, so nothing left can show the caller was
        # allowed it. The run, its suite, and the check all fall out until retention deletes them.
        temp = self._make_view("temp_orders")
        check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=temp.id,
            subject_name="temp_orders",
            check_type=CheckType.NOT_NULL,
            column_name="id",
            fingerprint=uuid4().hex,
        )
        suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=temp.id
        )
        api.record_check_run(
            self.team.id,
            suite_run=suite,
            quality_check=check,
            subject_type=SubjectType.VIEW,
            subject_uuid=temp.id,
            subject_name="temp_orders",
            check_type=CheckType.NOT_NULL,
            check_config={},
            referenced_subjects=[],
            check_fingerprint=check.fingerprint,
            status=CheckRunStatus.FAILED,
            failed_row_count=3,
        )
        self._deny_the_view()
        temp.delete()

        assert self.client.get(f"{self._checks_url(temp.id)}/").status_code == status.HTTP_403_FORBIDDEN
        assert self.client.get(f"{self._suite_runs_url(temp.id)}/").status_code == status.HTTP_403_FORBIDDEN

    def test_a_restricted_member_loses_an_orphaned_checks_row_from_the_project_list(self) -> None:
        # An orphan has no subject left to prove access against, so it fails closed for a member who
        # can be object-denied -- even when nothing is currently denied to them.
        temp = self._make_view("temp_orders")
        DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            saved_query_id=temp.id,
            subject_name="temp_orders",
            check_type=CheckType.NOT_NULL,
            column_name="id",
            fingerprint=uuid4().hex,
        )
        self._deny_the_view()
        self.view.delete()
        temp.delete()

        listed = self.client.get(f"/api/projects/{self.team.id}/data_quality_checks/")

        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert listed.json()["results"] == []

    def test_a_failure_building_the_readable_set_refuses_rather_than_leaks(self) -> None:
        # The snapshot walks every saved query; one malformed definition must not 500 the surface,
        # and must not fall through to serving rows it could not authorize.
        self._create_check()
        self._deny_the_view()

        with patch(
            "products.data_quality.backend.logic.subject_access.readable_subjects",
            side_effect=RuntimeError("boom"),
        ):
            response = self.client.get(f"{self.url}/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

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
