from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User

from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckSeverity,
    CheckType,
    SubjectType,
    SuiteRunTrigger,
)
from products.data_quality.backend.logic.notifications import (
    _blocking_referenced_names,
    _WarehouseSubjectResolver,
    notify_materialization_blocked,
)
from products.data_quality.backend.logic.runner import run_check
from products.data_quality.backend.logic.subject_access import referenced_subject_names
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.notifications.backend.facade.enums import TargetType

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

    def _resolver_for(self, check: DataQualityCheck) -> _WarehouseSubjectResolver:
        return _WarehouseSubjectResolver(
            self.team,
            check.subject_type,
            str(check.subject_uuid),
            referenced_names=referenced_subject_names(self.team.id, check.check_type, check.config),
        )

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
        resolved = self._resolver_for(check).resolve(TargetType.TEAM, str(self.team.id), self.team.id)

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

        resolved = self._resolver_for(check).resolve(TargetType.TEAM, str(self.team.id), self.team.id)

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

        resolved = self._resolver_for(check).resolve(TargetType.TEAM, str(self.team.id), self.team.id)

        assert self.user.id in resolved
        assert blocked.id not in resolved

    def test_members_denied_a_referenced_subject_do_not_get_the_blocked_materialization_count(self) -> None:
        # The blocked-materialization body counts the checks that failed, and one of them reads a
        # second view, so the count is an oracle over that view too. A member allowed the view being
        # materialized but denied the referenced one must be dropped.
        customers = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        blocked = User.objects.create_and_join(self.organization, "blocked-blocked@test.com", "password")
        self._deny_view_for_member(self.view, blocked)
        self._check(
            saved_query_id=customers.id,
            subject_name="customers",
            check_type=CheckType.RELATIONSHIPS,
            config={"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(self.view.id), "to_column": "id"},
            severity=CheckSeverity.ERROR,
            last_status=CheckRunStatus.FAILED,
        )

        with patch(CREATE_NOTIFICATION) as create_notification:
            notify_materialization_blocked(self.team.id, str(customers.id), "customers", 1, str(uuid4()))

        resolver = create_notification.call_args.args[0].resolver
        resolved = resolver.resolve(TargetType.TEAM, str(self.team.id), self.team.id)
        assert self.user.id in resolved
        assert blocked.id not in resolved

    def _blocking_relationships_check(self) -> tuple[DataWarehouseSavedQuery, str, DataQualityCheck]:
        # A materialization of "customers" blocked by a relationships check reading "orders", with the
        # suite run and check run the block left behind -- the state the notification reads.
        customers = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        check = self._check(
            saved_query_id=customers.id,
            subject_name="customers",
            check_type=CheckType.RELATIONSHIPS,
            column_name="",
            config={"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(self.view.id), "to_column": "id"},
            severity=CheckSeverity.ERROR,
            last_status=CheckRunStatus.FAILED,
        )
        job_id = str(uuid4())
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MATERIALIZATION, data_modeling_job_id=job_id
        )
        DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            quality_check=check,
            suite_run=suite_run,
            subject_type=SubjectType.VIEW,
            subject_uuid=customers.id,
            subject_name="customers",
            check_type=CheckType.RELATIONSHIPS,
            check_fingerprint=check.fingerprint,
            status=CheckRunStatus.FAILED,
            failed_row_count=2,
        )
        return customers, job_id, check

    @parameterized.expand(
        [
            ("untouched", {}),
            ("disabled_after_the_suite", {"enabled": False}),
            ("downgraded_after_the_suite", {"severity": CheckSeverity.WARN}),
            ("recovered_after_the_suite", {"last_status": CheckRunStatus.PASSED}),
            ("soft_deleted_after_the_suite", {"deleted": True}),
        ]
    )
    def test_editing_a_check_after_its_suite_cannot_drop_it_from_the_recipient_filter(self, _name, edit: dict) -> None:
        # The write path authorizes the declared subject only, so a member denied a referenced table
        # can still edit a check that reads it. Were the filter selected from enabled/severity/
        # last_status/deleted, that member could edit their own denial out of it between the suite
        # finishing and this notice being written, and still receive a count their check fed.
        customers, job_id, check = self._blocking_relationships_check()
        if edit:
            DataQualityCheck.objects.for_team(self.team.id).filter(pk=check.pk).update(**edit)

        assert _blocking_referenced_names(self.team.id, str(customers.id), job_id) == ["orders"]

    def test_a_failure_from_another_job_does_not_gate_this_blocks_recipients(self) -> None:
        # The counterpart: binding to the blocking suite must also stay narrow. A check that failed
        # under some earlier job never fed this count, so its referenced subjects must not
        # permanently drop members denied them from every later notice for the view.
        customers, _job_id, _check = self._blocking_relationships_check()
        later_job_id = str(uuid4())
        DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MATERIALIZATION, data_modeling_job_id=later_job_id
        )

        assert _blocking_referenced_names(self.team.id, str(customers.id), later_job_id) == []

    def test_a_block_with_no_resolvable_suite_falls_back_to_every_referencing_check(self) -> None:
        # Retention sweeps suite runs, and a definition can be hard-deleted or re-pointed. With
        # nothing left to bind the count to, the filter widens to every referencing check on the
        # subject rather than sending unfiltered.
        customers = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="customers", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
        )
        self._check(
            saved_query_id=customers.id,
            subject_name="customers",
            check_type=CheckType.RELATIONSHIPS,
            column_name="",
            config={"to_subject_type": SubjectType.VIEW, "to_subject_uuid": str(self.view.id), "to_column": "id"},
            enabled=False,
            deleted=True,
        )

        assert _blocking_referenced_names(self.team.id, str(customers.id), str(uuid4())) == ["orders"]

    def test_a_blocked_run_carries_a_dedupe_key_stable_per_job(self) -> None:
        # The block activity runs twice when a slow attempt hits its start-to-close timeout; both
        # attempts share the job id, so the notice carries a key stable across retries -- the unique
        # constraint behind it collapses the retry to one notice -- while a genuinely new block
        # (a different job) gets a new key and notifies again.
        job_id = str(uuid4())
        with patch(CREATE_NOTIFICATION) as create_notification:
            notify_materialization_blocked(self.team.id, str(self.view.id), "orders", 1, job_id)
            notify_materialization_blocked(self.team.id, str(self.view.id), "orders", 1, job_id)
            notify_materialization_blocked(self.team.id, str(self.view.id), "orders", 1, str(uuid4()))

        keys = [call.args[0].idempotency_key for call in create_notification.call_args_list]
        assert keys[0] is not None
        assert keys[0] == keys[1]
        assert keys[0] != keys[2]

    def test_a_notification_failure_does_not_fail_the_run(self) -> None:
        check = self._check()

        with patch(CREATE_NOTIFICATION, side_effect=RuntimeError("notifications down")):
            with patch(RUNNER_QUERY, return_value=_Response(4)):
                outcome = run_check(check, self.suite_run, self.team)

        assert outcome.status == CheckRunStatus.FAILED
