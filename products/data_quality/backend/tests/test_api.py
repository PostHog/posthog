from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun

from ee.models.rbac.access_control import AccessControl

START_SUITE = "products.data_quality.backend.logic.checks.sync_connect"
FLAG = "products.data_quality.backend.presentation.views.is_data_quality_checks_enabled"


class TestDataQualityCheckAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(team=self.team, name="orders", query={"kind": "HogQLQuery"})
        self.url = f"/api/projects/{self.team.id}/data_quality/checks"
        flag = patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_the_whole_surface_is_gated_on_the_feature_flag(self) -> None:
        with patch(FLAG, return_value=False):
            assert self.client.get(f"{self.url}/").status_code == status.HTTP_403_FORBIDDEN
            assert self.client.post(f"{self.url}/", self._payload()).status_code == status.HTTP_403_FORBIDDEN
            assert self.client.get(f"{self.url}/check_types/").status_code == status.HTTP_403_FORBIDDEN

    def _payload(self, **overrides) -> dict:
        return {
            "subject_type": SubjectType.VIEW,
            "subject_uuid": str(self.view.id),
            "check_type": CheckType.NOT_NULL,
            "column_name": "customer_id",
            **overrides,
        }

    def _create_check(self, **overrides) -> DataQualityCheck:
        response = self.client.post(f"{self.url}/", self._payload(**overrides))
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return DataQualityCheck.objects.for_team(self.team.id).get(id=response.json()["id"])

    def test_create_returns_the_fingerprint_and_re_creating_upserts(self) -> None:
        created = self.client.post(f"{self.url}/", self._payload())
        assert created.status_code == status.HTTP_201_CREATED
        assert created.json()["fingerprint"]

        again = self.client.post(f"{self.url}/", self._payload(description="clarified"))

        assert again.status_code == status.HTTP_200_OK
        assert again.json()["id"] == created.json()["id"]
        assert again.json()["description"] == "clarified"
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 1

    @parameterized.expand(
        [
            ("unknown_subject", {"subject_uuid": "1cd4a1ef-0000-0000-0000-0000000000ff"}),
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

    @parameterized.expand([("check_type",), ("column_name",), ("config",), ("subject_uuid",)])
    def test_the_assertion_cannot_be_edited_in_place(self, field: str) -> None:
        # Editing it would leave the fingerprint describing a different check, so later identical
        # creates would duplicate instead of upserting.
        check = self._create_check()
        new_value = {
            "check_type": CheckType.UNIQUE,
            "column_name": "total",
            "config": {"values": ["a"]},
            "subject_uuid": str(uuid4()),
        }[field]

        response = self.client.patch(f"{self.url}/{check.id}/", {field: new_value})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        check.refresh_from_db()
        assert str(getattr(check, field)) != str(new_value)

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

    def test_list_filters_by_subject(self) -> None:
        self._create_check()
        other_view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="refunds", query={"kind": "HogQLQuery"}
        )
        self.client.post(f"{self.url}/", self._payload(subject_uuid=str(other_view.id)))

        filtered = self.client.get(f"{self.url}/?subject_uuid={self.view.id}")

        assert [row["subject_uuid"] for row in filtered.json()["results"]] == [str(self.view.id)]

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
                subject_uuid=self.view.id,
                subject_name="orders",
                check_type=CheckType.NOT_NULL,
                column_name=f"col_{index}",
                fingerprint=uuid4().hex,
                severity=severity,
                last_status=last_status,
            )

        response = self.client.get(f"{self.url}/health/?subject_type={SubjectType.VIEW}&subject_uuid={self.view.id}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["health"] == expected
        assert response.json()["checks_total"] == len(states)

    def test_health_ignores_disabled_checks(self) -> None:
        # A disabled failing check must not drive the verdict, or health would read 'failing' while
        # checks_failing counts 0 -- the verdict and the counts have to agree.
        common = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "subject_uuid": self.view.id,
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

        response = self.client.get(f"{self.url}/health/?subject_type={SubjectType.VIEW}&subject_uuid={self.view.id}")

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

    def test_run_for_subject_records_the_subject_on_the_report(self) -> None:
        self._create_check()

        with patch(START_SUITE, return_value=MagicMock(start_workflow=AsyncMock())):
            response = self.client.post(
                f"{self.url}/run_for_subject/",
                {"subject_type": SubjectType.VIEW, "subject_uuid": str(self.view.id)},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["subject_uuid"] == str(self.view.id)

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
            ("create", lambda self: self.client.post(f"{self.url}/", self._payload())),
            (
                "run_for_subject",
                lambda self: self.client.post(
                    f"{self.url}/run_for_subject/",
                    {"subject_type": SubjectType.VIEW, "subject_uuid": str(self.view.id)},
                ),
            ),
            (
                "health",
                lambda self: self.client.get(
                    f"{self.url}/health/?subject_type={SubjectType.VIEW}&subject_uuid={self.view.id}"
                ),
            ),
        ]
    )
    def test_a_denied_subject_blocks_the_paths_that_name_it(self, _name: str, call) -> None:
        # Authoring, running, or reading health for a table the member cannot query would leak its
        # shape and observed counts. These paths take the subject in the request, so they 403.
        self._deny_the_view()

        assert call(self).status_code == status.HTTP_403_FORBIDDEN

    def test_denied_subject_checks_drop_out_of_list_and_detail(self) -> None:
        # safely_get_queryset hides checks on a denied subject, so both the list and the by-id
        # detail/run routes stop serving them -- the same subjects the information_schema loaders hide.
        denied = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.view.id,
            subject_name="orders",
            check_type=CheckType.NOT_NULL,
            column_name="customer_id",
            fingerprint=uuid4().hex,
        )
        allowed_view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            subject_uuid=allowed_view.id,
            subject_name="customers",
            check_type=CheckType.NOT_NULL,
            column_name="id",
            fingerprint=uuid4().hex,
        )
        self._deny_the_view()

        listed = self.client.get(f"{self.url}/")

        assert {row["subject_name"] for row in listed.json()["results"]} == {"customers"}
        assert self.client.get(f"{self.url}/{denied.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.post(f"{self.url}/{denied.id}/run/").status_code == status.HTTP_404_NOT_FOUND

    def test_suite_run_check_runs_drop_denied_subjects(self) -> None:
        # A suite run is not subject-scoped, so its check_runs must still hide runs for a denied
        # subject -- each carries the failed-row count and observed value.
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(team=self.team, trigger="manual")
        for name, subject_uuid in (("orders", self.view.id), ("customers", uuid4())):
            DataQualityCheckRun.objects.for_team(self.team.id).create(
                team=self.team,
                suite_run=suite_run,
                subject_type=SubjectType.VIEW,
                subject_uuid=subject_uuid,
                subject_name=name,
                check_type=CheckType.NOT_NULL,
                check_fingerprint=uuid4().hex,
                status=CheckRunStatus.FAILED,
                failed_row_count=3,
            )
        self._deny_the_view()

        url = f"/api/projects/{self.team.id}/data_quality/check_suite_runs/{suite_run.id}/check_runs/"
        response = self.client.get(url)

        assert {row["subject_name"] for row in response.json()} == {"customers"}

    @parameterized.expand(
        [
            ("custom_sql", CheckType.CUSTOM_SQL, "", {"query": "SELECT 1 FROM orders"}),
            ("relationships", CheckType.RELATIONSHIPS, "customer_id", None),
        ]
    )
    def test_a_denied_referenced_subject_blocks_authoring(self, _name, check_type, column_name, config) -> None:
        # The declared subject is not the only one a check reads: custom_sql selects arbitrary tables
        # and relationships names a second subject. Authoring one that reads the denied "orders" from an
        # allowed subject must 403 -- the worker runs it with team scope only, a count oracle otherwise.
        allowed = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        if config is None:
            config = {"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(self.view.id), "to_column": "id"}
        self._deny_the_view()

        response = self.client.post(
            f"{self.url}/",
            self._payload(subject_uuid=str(allowed.id), check_type=check_type, column_name=column_name, config=config),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert DataQualityCheck.objects.for_team(self.team.id).count() == 0

    @parameterized.expand(
        [
            ("run", lambda self, check: self.client.post(f"{self.url}/{check.id}/run/")),
            (
                "run_for_subject",
                lambda self, check: self.client.post(
                    f"{self.url}/run_for_subject/",
                    {"subject_type": check.subject_type, "subject_uuid": str(check.subject_uuid)},
                ),
            ),
            ("runs", lambda self, check: self.client.get(f"{self.url}/{check.id}/runs/")),
        ]
    )
    def test_a_denied_referenced_subject_blocks_triggering_and_reading_history(self, _name, call) -> None:
        # The declared subject stays allowed, so the check is visible -- but its custom_sql reads the
        # denied "orders". Triggering it (run, run_for_subject) and reading its run history (runs, which
        # exposes counts from scheduled executions) gate on every subject it references, not just the
        # one named in the request.
        allowed = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.VIEW,
            subject_uuid=allowed.id,
            subject_name="customers",
            check_type=CheckType.CUSTOM_SQL,
            config={"query": "SELECT 1 FROM orders"},
            fingerprint=uuid4().hex,
        )
        self._deny_the_view()

        assert call(self, check).status_code == status.HTTP_403_FORBIDDEN

    def test_denied_single_subject_suite_runs_drop_out_of_list_and_detail(self) -> None:
        # A single-subject suite carries that subject_uuid alongside its passed/failed counts, a
        # per-subject outcome the member must not read for a denied table, so list and detail hide it.
        allowed = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        denied_suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=self.view.id
        )
        allowed_suite = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger="manual", subject_type=SubjectType.VIEW, subject_uuid=allowed.id
        )
        self._deny_the_view()

        base = f"/api/projects/{self.team.id}/data_quality/check_suite_runs"
        listed = self.client.get(f"{base}/")

        assert {row["id"] for row in listed.json()["results"]} == {str(allowed_suite.id)}
        assert self.client.get(f"{base}/{denied_suite.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.get(f"{base}/{allowed_suite.id}/").status_code == status.HTTP_200_OK

    @parameterized.expand([("create",), ("run",), ("runs",)])
    def test_query_denied_members_cannot_author_or_execute_checks(self, surface: str) -> None:
        # A check executes HogQL and its result columns are a count oracle over warehouse rows, so
        # data_quality access alone must not be enough.
        check = self._create_check()
        AccessControl.objects.create(team=self.team, resource="query", access_level="none")
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "access"}]
        self.organization.save()

        if surface == "create":
            response = self.client.post(f"{self.url}/", self._payload(column_name="total"))
        elif surface == "run":
            response = self.client.post(f"{self.url}/{check.id}/run/")
        else:
            response = self.client.get(f"{self.url}/{check.id}/runs/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_another_projects_checks_are_not_visible(self) -> None:
        check = self._create_check()
        other_team = self.create_team_with_organization(self.organization)

        response = self.client.get(f"/api/projects/{other_team.id}/data_quality/checks/{check.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
