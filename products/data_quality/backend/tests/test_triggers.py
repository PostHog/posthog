from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Node
from products.data_quality.backend.facade.contracts import QUALITY_AUDIT_GATE, QUALITY_AUDIT_SKIP, QUALITY_AUDIT_WARN
from products.data_quality.backend.facade.enums import CheckSeverity, CheckType, SubjectType
from products.data_quality.backend.logic.triggers import (
    materialization_audit_mode,
    materialization_checks_needed,
    source_sync_checks_needed,
)
from products.data_quality.backend.models import DataQualityCheck, TeamDataQualityConfig

TRIGGER_FLAG = "products.data_quality.backend.logic.triggers.is_data_quality_checks_enabled_for_team_id"


class TestTriggerGates(BaseTest):
    """The gates the pipelines consult before spending a workflow on a suite."""

    def setUp(self) -> None:
        super().setUp()
        self.view = DataWarehouseSavedQuery.objects.create(team=self.team, name="orders", query="SELECT 1")
        self.node = Node.objects.create(
            team=self.team, dag=DAG.objects.create(team=self.team, name="dag"), saved_query=self.view, name="orders"
        )
        flag = patch(TRIGGER_FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

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
            ("no_check_on_the_subject", None, True),
            ("a_disabled_check", {"enabled": False}, True),
            ("a_deleted_check", {"deleted": True}, True),
            ("a_runnable_check_but_the_flag_is_off", {}, False),
        ]
    )
    def test_no_suite_is_needed(self, _name, check_kwargs, flag_on) -> None:
        if check_kwargs is not None:
            self._check(**check_kwargs)

        with patch(TRIGGER_FLAG, return_value=flag_on):
            assert materialization_checks_needed(self.team.id, [str(self.node.id)]) is False

    def test_a_materialized_node_with_a_runnable_check_needs_a_suite(self) -> None:
        self._check()

        assert materialization_checks_needed(self.team.id, [str(self.node.id)]) is True

    def test_a_node_without_a_saved_query_needs_no_suite(self) -> None:
        self._check()
        source_node = Node.objects.create(
            team=self.team, dag=DAG.objects.create(team=self.team, name="other"), name="raw_events"
        )

        assert materialization_checks_needed(self.team.id, [str(source_node.id)]) is False

    def test_a_synced_table_with_a_runnable_check_needs_a_suite(self) -> None:
        table_id = uuid4()
        self._check(saved_query_id=None, table_id=table_id, subject_type=SubjectType.TABLE)

        assert source_sync_checks_needed(self.team.id, table_id) is True

    @parameterized.expand(
        [
            ("the_flag_is_off", {"severity": CheckSeverity.ERROR}, True, False, QUALITY_AUDIT_SKIP),
            ("the_subject_has_no_check", None, True, True, QUALITY_AUDIT_SKIP),
            ("the_team_never_configured_a_gate", {"severity": CheckSeverity.ERROR}, None, True, QUALITY_AUDIT_WARN),
            ("the_team_turned_the_gate_off", {"severity": CheckSeverity.ERROR}, False, True, QUALITY_AUDIT_WARN),
            ("every_check_only_warns", {"severity": CheckSeverity.WARN}, True, True, QUALITY_AUDIT_WARN),
            ("a_check_can_block", {"severity": CheckSeverity.ERROR}, True, True, QUALITY_AUDIT_GATE),
        ]
    )
    def test_audit_mode(self, _name, check_kwargs, gate_setting, flag_on, expected) -> None:
        if check_kwargs is not None:
            self._check(**check_kwargs)
        if gate_setting is None:
            TeamDataQualityConfig.objects.filter(team_id=self.team.id).delete()
        else:
            TeamDataQualityConfig.objects.update_or_create(
                team=self.team, defaults={"gate_materialization_on_checks": gate_setting}
            )

        with patch(TRIGGER_FLAG, return_value=flag_on):
            assert materialization_audit_mode(self.team.id, self.view.id) == expected
