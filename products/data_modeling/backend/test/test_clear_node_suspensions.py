from io import StringIO
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from products.data_modeling.backend.logic.node_suspension import is_node_suspended, suspension_state
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.models.data_modeling_job import DataModelingJobEngine
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node

CLICKHOUSE = DataModelingJobEngine.CLICKHOUSE
TRINO = DataModelingJobEngine.MANAGED_WAREHOUSE
OVERFLOW = "Code: 407. DB::Exception: Can't compare decimal number due to overflow. (DECIMAL_OVERFLOW)"
CUSTOMER_ERROR = "Code: 47. DB::Exception: Unknown expression identifier 'foo'"
INCIDENT = "2026-09-30T00:30:00+00:00"


@pytest.mark.django_db
class TestClearNodeSuspensions(BaseTest):
    def _node(self, markers: dict[str, tuple[str, str]]) -> Node:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=f"model_{uuid4().hex[:8]}",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None
        node.properties = {
            **(node.properties or {}),
            "system": {
                "suspended": {
                    engine: {"at": at, "reason": reason, "job_id": str(uuid4()), "query_fingerprint": None}
                    for engine, (reason, at) in markers.items()
                }
            },
        }
        node.save()
        return node

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("clear_node_suspensions", *args, stdout=out)
        return out.getvalue()

    @parameterized.expand(
        [
            ("by_reason_and_engine", ["--engine", "clickhouse", "--reason-contains", "DECIMAL_OVERFLOW"]),
            (
                "by_reason_inside_window",
                [
                    "--reason-contains",
                    "DECIMAL_OVERFLOW",
                    "--engine",
                    "clickhouse",
                    "--suspended-from",
                    "2026-09-29T00:00:00+00:00",
                    "--suspended-to",
                    "2026-10-01T00:00:00+00:00",
                ],
            ),
        ]
    )
    def test_clears_only_the_selected_markers(self, _name: str, selection: list[str]) -> None:
        incident = self._node({CLICKHOUSE: (OVERFLOW, INCIDENT), TRINO: (CUSTOMER_ERROR, INCIDENT)})
        same_error_outside_window = self._node({CLICKHOUSE: (OVERFLOW, "2026-10-12T00:00:00+00:00")})
        customer = self._node({CLICKHOUSE: (CUSTOMER_ERROR, INCIDENT)})
        expected_to_survive = [(customer, CLICKHOUSE), (incident, TRINO)]
        if "--suspended-from" in selection:
            expected_to_survive.append((same_error_outside_window, CLICKHOUSE))

        dry_run = self._run(*selection)

        incident.refresh_from_db()
        assert is_node_suspended(incident, CLICKHOUSE)
        assert "Dry run" in dry_run

        self._run(*selection, "--apply")

        for node, engine in expected_to_survive:
            node.refresh_from_db()
            assert is_node_suspended(node, engine), (node.id, engine)
        incident.refresh_from_db()
        assert not is_node_suspended(incident, CLICKHOUSE)
        assert incident.properties["system"]["suspension_reset"][CLICKHOUSE]["by"] == "operator"

    def test_selects_by_saved_query_across_engines(self) -> None:
        node = self._node({CLICKHOUSE: (OVERFLOW, INCIDENT), TRINO: (CUSTOMER_ERROR, INCIDENT)})
        other = self._node({CLICKHOUSE: (OVERFLOW, INCIDENT)})

        self._run("--saved-query-ids", str(node.saved_query_id), "--apply")

        node.refresh_from_db()
        other.refresh_from_db()
        assert suspension_state(node) == {}
        assert is_node_suspended(other, CLICKHOUSE)

    @parameterized.expand(
        [
            ("no_selector", ["--engine", "clickhouse"], "Name the set"),
            ("empty_reason", ["--reason-contains", ""], "empty"),
            (
                "blank_reason_among_others",
                ["--reason-contains", "DECIMAL_OVERFLOW", "--reason-contains", "  "],
                "empty",
            ),
        ]
    )
    def test_refuses_without_a_real_selector(self, _name: str, args: list[str], message: str) -> None:
        node = self._node({CLICKHOUSE: (OVERFLOW, INCIDENT)})

        with pytest.raises(CommandError, match=message):
            self._run(*args, "--apply")

        node.refresh_from_db()
        assert is_node_suspended(node, CLICKHOUSE)
