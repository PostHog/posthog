from io import StringIO

import pytest

from django.core.management import call_command

from posthog.models import Organization, Team

from products.data_modeling.backend.logic.node_suspension import is_node_suspended, mark_node_suspended
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.data_modeling_job import DataModelingJobEngine
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType

pytestmark = pytest.mark.django_db

COMMAND = "resume_duckgres_suspensions"


def _suspended_node(team: Team, *, engines: list[str]) -> Node:
    dag = DAG.objects.create(team=team, name=f"dag-{team.pk}")
    saved_query = DataWarehouseSavedQuery.objects.create(
        team=team, name=f"model_{team.pk}", query={"query": "SELECT 1"}
    )
    node = Node.objects.create(
        team=team, dag=dag, saved_query=saved_query, name=f"model-{team.pk}", type=NodeType.MAT_VIEW
    )
    for engine in engines:
        mark_node_suspended(node, engine=engine, reason="boom", job_id="job-1")
    node.save(update_fields=["properties"])
    return node


def _team() -> Team:
    return Team.objects.create(organization=Organization.objects.create(name="org"), name="t")


def test_resumes_duckgres_but_keeps_other_engines() -> None:
    team = _team()
    node = _suspended_node(team, engines=[DataModelingJobEngine.DUCKGRES.value, DataModelingJobEngine.CLICKHOUSE.value])

    out = StringIO()
    call_command(COMMAND, stdout=out)

    node.refresh_from_db()
    assert is_node_suspended(node, DataModelingJobEngine.DUCKGRES.value) is False
    assert is_node_suspended(node, DataModelingJobEngine.CLICKHOUSE.value) is True
    assert "Resumed 1 of 1" in out.getvalue()


def test_team_scope_and_dry_run_leave_other_teams_suspended() -> None:
    target_team, other_team = _team(), _team()
    target_node = _suspended_node(target_team, engines=[DataModelingJobEngine.DUCKGRES.value])
    other_node = _suspended_node(other_team, engines=[DataModelingJobEngine.DUCKGRES.value])

    dry_out = StringIO()
    call_command(COMMAND, "--dry-run", stdout=dry_out)
    target_node.refresh_from_db()
    assert is_node_suspended(target_node, DataModelingJobEngine.DUCKGRES.value) is True
    assert "Would resume 2" in dry_out.getvalue()

    call_command(COMMAND, "--team-id", str(target_team.pk), stdout=StringIO())
    target_node.refresh_from_db()
    other_node.refresh_from_db()
    assert is_node_suspended(target_node, DataModelingJobEngine.DUCKGRES.value) is False
    assert is_node_suspended(other_node, DataModelingJobEngine.DUCKGRES.value) is True
