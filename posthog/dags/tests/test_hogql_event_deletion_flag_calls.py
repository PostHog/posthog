from contextlib import nullcontext
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.test import override_settings

import dagster

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable

from posthog.dags.data_deletion_requests import HogQLEventDeletionExecutor, HogQLEventRemovalContext
from posthog.data_deletion import _column_sources
from posthog.models.instance_setting import override_instance_config

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

_EVENTS_ONLY = "SELECT uuid FROM events WHERE distinct_id = 'x'"
_MIXED_FLAG_CALLS = "SELECT uuid FROM events WHERE event IN ('$pageview', '$feature_flag_called') AND distinct_id = 'x'"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "mode", "overrides", "refused"),
    [
        pytest.param(_EVENTS_ONLY, FlagEvaluationsMode.EVENTS, {"native_events": False}, False, id="mode-0-events"),
        pytest.param(
            _EVENTS_ONLY, FlagEvaluationsMode.READ_FLAG_EVALUATIONS, {"native_events": False}, False, id="mode-1-events"
        ),
        pytest.param(_EVENTS_ONLY, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, {}, True, id="mode-2-events"),
        pytest.param(
            _EVENTS_ONLY,
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {"keep_events_writes": True, "force_events_reads": True},
            True,
            id="mode-2-events-reads-forced-to-events",
        ),
        pytest.param(_EVENTS_ONLY, FlagEvaluationsMode.EVENTS, {"native_events": True}, True, id="native-events"),
        pytest.param(
            "SELECT uuid FROM events WHERE distinct_id IN (SELECT distinct_id FROM posthog.flag_evaluations)",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            True,
            id="flag-evaluations-only-in-where",
        ),
        pytest.param(
            "SELECT e.uuid FROM events e JOIN posthog.flag_evaluations f ON e.distinct_id = f.distinct_id",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            True,
            id="flag-evaluations-only-joined",
        ),
        pytest.param(
            "SELECT uuid FROM events UNION ALL SELECT flag_evaluation_person_id AS uuid FROM posthog.flag_evaluations",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            True,
            id="flag-evaluations-other-uuid-column",
        ),
        pytest.param(
            _MIXED_FLAG_CALLS,
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {"union_disabled": True},
            True,
            id="mixed-flag-calls-union-disabled",
        ),
        pytest.param(
            "SELECT uuid FROM events WHERE event = '$feature_flag_called' AND distinct_id = 'x'",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            False,
            id="flag-calls-swapped",
        ),
        pytest.param(
            _MIXED_FLAG_CALLS, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, {}, False, id="mixed-flag-calls-union"
        ),
        pytest.param(
            f"{_EVENTS_ONLY} UNION ALL SELECT uuid FROM posthog.flag_evaluations WHERE distinct_id = 'x'",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            False,
            id="explicit-union",
        ),
        pytest.param(
            f"{_EVENTS_ONLY} UNION ALL SELECT uuid FROM posthog.flag_evaluations WHERE false",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            False,
            id="flag-calls-opted-out",
        ),
        pytest.param(
            f"{_EVENTS_ONLY} UNION ALL SELECT toUUID(toString(uuid)) FROM posthog.flag_evaluations",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            True,
            id="flag-evaluations-uuid-computed",
        ),
        pytest.param(
            f"{_EVENTS_ONLY} INTERSECT SELECT uuid FROM posthog.flag_evaluations WHERE distinct_id = 'x'",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            True,
            id="flag-evaluations-intersected",
        ),
        pytest.param(
            f"SELECT uuid FROM ({_EVENTS_ONLY} EXCEPT SELECT uuid FROM posthog.flag_evaluations WHERE distinct_id = 'x')",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            True,
            id="flag-evaluations-excepted-in-subquery",
        ),
        pytest.param(
            "WITH f AS (SELECT uuid AS u FROM posthog.flag_evaluations) "
            "SELECT uuid FROM events UNION ALL SELECT u FROM (SELECT u FROM f)",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            False,
            id="flag-evaluations-through-cte-and-subquery",
        ),
        pytest.param(
            "SELECT toUUID('01234567-89ab-cdef-0123-456789abcdef')",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            False,
            id="no-events-read",
        ),
        pytest.param(
            "SELECT q.uuid FROM (SELECT uuid, flag_evaluation_person_id FROM posthog.flag_evaluations "
            "UNION ALL SELECT uuid AS a, uuid AS b FROM events) AS q(flag_evaluation_person_id, uuid)",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            True,
            id="column-aliases-rename-a-union",
        ),
        pytest.param(
            "SELECT q.flag_evaluation_person_id FROM (SELECT uuid, flag_evaluation_person_id FROM "
            "posthog.flag_evaluations UNION ALL SELECT uuid AS a, uuid AS b FROM events) "
            "AS q(flag_evaluation_person_id, uuid)",
            FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            {},
            False,
            id="column-aliases-rename-a-union-to-flag-uuid",
        ),
    ],
)
def test_hogql_event_deletion_executor_refuses_a_query_that_misses_flag_calls_only_in_flag_evaluations(
    team, user, query, mode, overrides, refused
):
    OrganizationFeatureFlagsConfig.objects.update_or_create(
        organization=team.organization,
        defaults={
            "flag_evaluations_mode": mode,
            "keep_writing_flag_calls_to_events": overrides.get("keep_events_writes", False),
        },
    )
    deletion_request = HogQLEventRemovalContext(
        request_id=str(uuid4()), team_id=team.pk, created_by_id=user.pk, query=query, variables={}
    )

    with (
        override_instance_config("FLAG_EVALUATIONS_UNION_DISABLED", overrides.get("union_disabled", False)),
        override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", overrides.get("force_events_reads", False)),
        (
            override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=overrides["native_events"])
            if "native_events" in overrides
            else nullcontext()
        ),
        patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=False),
        patch("products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled", return_value=True),
        patch("posthog.dags.data_deletion_requests.sync_execute", return_value=1) as execute,
    ):
        if refused:
            with pytest.raises(dagster.Failure, match=r"UNION ALL SELECT uuid FROM posthog\.flag_evaluations"):
                HogQLEventDeletionExecutor(deletion_request).execute()
        else:
            assert HogQLEventDeletionExecutor(deletion_request).execute() == 1

    assert execute.called is not refused


def test_column_sources_follows_a_shared_query_type_once():
    events_type = ast.TableType(table=EventsTable())
    query_type: ast.TableType | ast.SelectSetQueryType = events_type
    for _ in range(16):
        level = ast.SelectQueryType(columns={"uuid": ast.FieldType(name="uuid", table_type=query_type)})
        query_type = ast.SelectSetQueryType(types=[level, level], columns={"uuid": ast.UUIDType()})

    sources = list(_column_sources(query_type, "uuid", seen=set()))

    assert len(sources) == 1
    assert sources == [(events_type.table, "uuid")]
