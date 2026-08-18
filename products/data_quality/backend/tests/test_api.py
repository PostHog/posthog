from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import CheckRunStatus, CheckSeverity, CheckType, SubjectType
from products.data_quality.backend.models import DataQualityCheck, DataQualitySuiteRun

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
