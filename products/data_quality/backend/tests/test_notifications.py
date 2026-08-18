from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckSeverity,
    CheckType,
    SubjectType,
    SuiteRunTrigger,
)
from products.data_quality.backend.logic.notifications import _WarehouseSubjectResolver
from products.data_quality.backend.logic.runner import run_check
from products.data_quality.backend.models import DataQualityCheck, DataQualitySuiteRun
from products.notifications.backend.facade.enums import TargetType

from ee.models.rbac.access_control import AccessControl

RUNNER_QUERY = "products.data_quality.backend.logic.runner.execute_hogql_query"
CREATE_NOTIFICATION = "products.data_quality.backend.logic.notifications.create_notification"


class _Response:
    def __init__(self, failure_count: int) -> None:
        self.columns = ["failure_count", "observed_value"]
        self.results = [[failure_count, failure_count]]


class TestDataQualityNotifications(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch(
            "products.data_quality.backend.logic.notifications.is_data_quality_checks_enabled_for_team_id",
            return_value=True,
        )
        flag.start()
        self.addCleanup(flag.stop)
        self.view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        self.suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MANUAL
        )

    def _check(self, **kwargs) -> DataQualityCheck:
        defaults = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "saved_query_id": self.view.id,
            "subject_name": "orders",
            "check_type": CheckType.NOT_NULL,
            "column_name": "customer_id",
            "fingerprint": uuid4().hex,
        }
        return DataQualityCheck.objects.for_team(self.team.id).create(**{**defaults, **kwargs})

    @parameterized.expand(
        [
            ("first_failure", "", CheckSeverity.ERROR, 3, 1),
            ("still_failing", CheckRunStatus.FAILED, CheckSeverity.ERROR, 3, 0),
            ("recovered_then_failed_again", CheckRunStatus.PASSED, CheckSeverity.ERROR, 3, 1),
            ("warn_severity_failure", "", CheckSeverity.WARN, 3, 0),
            ("passing", "", CheckSeverity.ERROR, 0, 0),
            ("recovery", CheckRunStatus.FAILED, CheckSeverity.ERROR, 0, 0),
        ]
    )
    def test_only_a_pass_to_fail_edge_on_an_error_check_notifies(
        self, _name, previous_status: str, severity: CheckSeverity, failure_count: int, expected_calls: int
    ) -> None:
        check = self._check(last_status=previous_status, severity=severity)

        with patch(CREATE_NOTIFICATION) as create_notification:
            with patch(RUNNER_QUERY, return_value=_Response(failure_count)):
                run_check(check, self.suite_run, self.team)

        assert create_notification.call_count == expected_calls

    def test_the_notification_names_the_subject_and_the_failing_row_count(self) -> None:
        check = self._check()

        with patch(CREATE_NOTIFICATION) as create_notification:
            with patch(RUNNER_QUERY, return_value=_Response(4)):
                run_check(check, self.suite_run, self.team)

        payload = create_notification.call_args.args[0]
        assert payload.title == "Data quality check failed on orders"
        assert "4 failing rows" in payload.body
        # The notification points at the warehouse subject object, not the check row.
        assert payload.resource_id == str(check.subject_uuid)

    def test_recipients_are_filtered_to_members_who_can_see_warehouse_objects(self) -> None:
        # The body names a table and column, so it must not reach members denied warehouse access.
        check = self._check()

        with patch(CREATE_NOTIFICATION) as create_notification:
            with patch(RUNNER_QUERY, return_value=_Response(4)):
                run_check(check, self.suite_run, self.team)

        assert create_notification.call_args.args[0].resource_type == "warehouse_objects"

    @patch("products.notifications.backend.resolvers.UserAccessControl")
    def test_members_without_query_access_do_not_get_the_failing_row_count(self, mock_uac_cls) -> None:
        # The body's failing-row count is a count oracle over warehouse rows the run-history API gates
        # behind query access, so a member with warehouse access but no query access must be dropped.
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        denied = User.objects.create_and_join(self.organization, "no-query@test.com", "password")

        class FakeUAC:
            def __init__(self, user, team) -> None:
                self._user_id = user.id

            @property
            def access_controls_supported(self) -> bool:
                return True

            def check_access_level_for_resource(self, resource, level) -> bool:
                # Everyone can see warehouse objects; only the denied user lacks query access.
                return resource != "query" or self._user_id != denied.id

        mock_uac_cls.side_effect = FakeUAC

        check = self._check()
        resolved = _WarehouseSubjectResolver(
            self.team, check.subject_type, str(check.subject_uuid), check=check
        ).resolve(TargetType.TEAM, str(self.team.id), self.team.id)

        assert self.user.id in resolved
        assert denied.id not in resolved

    def test_members_denied_the_subject_object_do_not_get_the_notification(self) -> None:
        # A member with general warehouse and query access but an explicit denial on THIS view must
        # not receive its name, column, or failing-row count -- the built-in resource-level filter
        # only asks whether they can see warehouse objects at all.
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        allowed = User.objects.create_and_join(self.organization, "allowed@test.com", "password")
        blocked = User.objects.create_and_join(self.organization, "blocked@test.com", "password")
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(self.view.id),
            organization_member=OrganizationMembership.objects.get(organization=self.organization, user=blocked),
            access_level="none",
        )
        check = self._check()

        resolved = _WarehouseSubjectResolver(
            self.team, check.subject_type, str(check.subject_uuid), check=check
        ).resolve(TargetType.TEAM, str(self.team.id), self.team.id)

        assert allowed.id in resolved
        assert blocked.id not in resolved

    def _deny_view_for_member(self, view, member: User) -> None:
        # Deny one member object-level access to a view the way the HogQL database sees it, so
        # denied_subject_names() picks it up -- the same setup the REST run-history tests use.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(view.id),
            organization_member=OrganizationMembership.objects.get(organization=self.organization, user=member),
            access_level="none",
        )
        flag = patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda name, *a, **k: name == "hogql-warehouse-access-control",
        )
        flag.start()
        self.addCleanup(flag.stop)
        cache.clear()

    @parameterized.expand(
        [
            ("custom_sql", CheckType.CUSTOM_SQL, "", {"query": "SELECT 1 FROM orders"}),
            ("relationships", CheckType.RELATIONSHIPS, "customer_id", None),
        ]
    )
    def test_members_denied_a_referenced_subject_do_not_get_the_notification(
        self, _name, check_type, column_name, config
    ) -> None:
        # A relationships check reads a target subject and a custom_sql check reads arbitrary tables,
        # so the failing-row count is a count oracle over those too. A member allowed the declared
        # subject ("customers") but denied a referenced one ("orders") must be dropped, matching the
        # run-history endpoint -- while an admin, who is denied nothing, still receives it.
        customers = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        if config is None:
            config = {"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(self.view.id), "to_column": "id"}
        blocked = User.objects.create_and_join(self.organization, "blocked-ref@test.com", "password")
        self._deny_view_for_member(self.view, blocked)
        check = self._check(
            saved_query_id=customers.id,
            subject_name="customers",
            check_type=check_type,
            column_name=column_name,
            config=config,
        )

        resolved = _WarehouseSubjectResolver(
            self.team, check.subject_type, str(check.subject_uuid), check=check
        ).resolve(TargetType.TEAM, str(self.team.id), self.team.id)

        assert self.user.id in resolved
        assert blocked.id not in resolved

    def test_a_notification_failure_does_not_fail_the_run(self) -> None:
        check = self._check()

        with patch(CREATE_NOTIFICATION, side_effect=RuntimeError("notifications down")):
            with patch(RUNNER_QUERY, return_value=_Response(4)):
                outcome = run_check(check, self.suite_run, self.team)

        assert outcome.status == CheckRunStatus.FAILED
