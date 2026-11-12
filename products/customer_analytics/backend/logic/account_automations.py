import re
import gzip
import base64
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import groupby
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.paging import Page, PageRequest
from posthog.schema_enums import ProductKey

from products.customer_analytics.backend.facade.contracts import AccountAutomation
from products.workflows.backend.facade.api import get_workflow_names
from products.workflows.backend.facade.contracts import WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.facade.workflows import get_workflow

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


MAX_RUN_LOG_ENTRIES = 200
WORKFLOW_FAILURE_PATTERN = (
    r"^(?:\[Action:[^\]\r\n]+\] (?:Errored:|Skipped due to filter conditions$|Skipping send:"
    r"|Recipient has opted out, skipping message delivery\.$)"
    r"|Workflow trigger did not match the event\.$"
    r"|This workflow triggers on [^\r\n]* would not trigger (?:this workflow|it)\.$"
    r"|This trigger's filters do not name any internal events, so no event would trigger this workflow\.$"
    r"|Messages PostHog's own connected Slack app posted would not trigger this workflow\.$"
    r"|Activity from PostHog's own GitHub App would not trigger this workflow\.$)"
)
WORKFLOW_FAILURE_EVIDENCE = "Workflow step failed"


def is_workflow_failure(message: str) -> bool:
    return message == WORKFLOW_FAILURE_EVIDENCE or re.match(WORKFLOW_FAILURE_PATTERN, message) is not None


@frozen
class AccountRunsQuery:
    count_sql: str
    page_sql: str
    parameters: dict[str, object]


@frozen
class WorkflowStep:
    action_id: str
    action_type: str
    name: str


@frozen
class CompletedWorkflowStep:
    action_id: str | None
    completed_at: datetime


def get_last_completed_step(
    logs: Sequence[tuple[datetime, str]], *, exit_action_ids: set[str]
) -> CompletedWorkflowStep | None:
    completed_step = None
    executing = False
    executing_ids: set[str] = set()
    for timestamp, entries in groupby(logs, key=lambda entry: entry[0]):
        messages = [message for _, message in entries]
        started_ids = {
            message.removeprefix("Executing action ").removeprefix("[Action:").removesuffix("]")
            for message in messages
            if message.startswith("Executing action ")
        }
        started = bool(started_ids)
        failed_or_skipped = any(is_workflow_failure(message) for message in messages)
        finished = "Workflow completed" in messages
        moved_ids = {
            message.removeprefix("Workflow moved to action ").removeprefix("[Action:").removesuffix("]")
            for message in messages
            if message.startswith("Workflow moved to action ")
        }
        moved = bool(moved_ids)
        exit_completed = finished and bool((started_ids or executing_ids) & exit_action_ids)
        if (executing or started) and (moved or exit_completed) and not failed_or_skipped:
            completed_ids = (
                (started_ids | executing_ids) & exit_action_ids
                if exit_completed
                else (started_ids | executing_ids) - moved_ids
            )
            completed_step = CompletedWorkflowStep(
                action_id=next(iter(completed_ids)) if len(completed_ids) == 1 else None,
                completed_at=timestamp,
            )
        if failed_or_skipped or moved or finished:
            executing = started and not failed_or_skipped and not finished
        elif started:
            executing = True
        if started or moved or finished:
            executing_ids = started_ids
    return completed_step


def get_expected_resume_at(
    logs: Sequence[tuple[datetime, str]], *, now: datetime, delay_action_ids: set[str]
) -> datetime | None:
    resume_at = None
    current_action_id = None
    prefix = "Workflow will pause until "
    for _, entries in groupby(logs, key=lambda entry: entry[0]):
        messages = [message for _, message in entries]
        pauses = [message.removeprefix(prefix) for message in messages if message.startswith(prefix)]
        action_ids = {
            message.removeprefix(action_prefix).removeprefix("[Action:").removesuffix("]")
            for message in messages
            for action_prefix in ("Executing action ", "Workflow moved to action ")
            if message.startswith(action_prefix)
        }
        if action_ids:
            current_action_id = next(iter(action_ids)) if len(action_ids) == 1 else None
        if any(
            message.startswith("Executing action ")
            or message.startswith("Workflow moved to action ")
            or message == "Workflow completed"
            or is_workflow_failure(message)
            for message in messages
        ):
            resume_at = None
        if pauses:
            resume_at = None
        if (
            current_action_id in delay_action_ids
            and len(pauses) == 1
            and not any(
                message.startswith("Workflow moved to action ")
                or message == "Workflow completed"
                or is_workflow_failure(message)
                for message in messages
            )
        ):
            try:
                parsed = datetime.fromisoformat(pauses[0])
                resume_at = parsed if parsed.tzinfo is not None else None
            except ValueError:
                resume_at = None
    return resume_at if resume_at is not None and resume_at > now else None


def get_account_runs_query(
    *, team: Team, account_id: str, external_id: str | None, workflow_ids: set[str]
) -> AccountRunsQuery:
    after = timezone.now() - timedelta(days=30)
    context = HogQLContext(team_id=team.pk, team=team, enable_select_queries=True, limit_top_select=False)
    event_query, _ = prepare_and_print_ast(
        parse_select(
            """SELECT toString(uuid) FROM events
            WHERE startsWith(event, '$account_')
                AND (properties.account_id = {account_id}
                    OR (empty(coalesce(toString(properties.account_id), '')) AND {has_external_id}
                        AND properties.account_external_id = {external_id}))
                AND toString(uuid) IN (
                    SELECT event_uuid FROM posthog.hog_invocation_results
                    WHERE function_kind = 'hog_flow' AND function_id IN {workflow_ids}
                        AND scheduled_at >= {after} AND event_uuid != ''
                )""",
            placeholders={
                "account_id": ast.Constant(value=account_id),
                "has_external_id": ast.Constant(value=external_id is not None),
                "external_id": ast.Constant(value=external_id or ""),
                "workflow_ids": ast.Constant(value=list(workflow_ids)),
                "after": ast.Constant(value=after),
            },
        ),
        context=context,
        dialect="clickhouse",
    )
    sql = f"""WITH candidates AS (
            SELECT function_id, invocation_id FROM hog_invocation_results
            WHERE team_id = %(team_id)s AND function_kind = 'hog_flow'
                AND function_id IN %(workflow_ids)s AND scheduled_at >= %(after)s
                AND (distinct_id IN %(identities)s OR event_uuid GLOBAL IN ({event_query}))
        ), latest_runs AS (
            SELECT function_id, invocation_id,
                argMax(tuple(status, first_scheduled_at, is_deleted, event_uuid,
                    parent_run_id, distinct_id, invocation_globals), version) AS latest
            FROM hog_invocation_results
            WHERE team_id = %(team_id)s AND function_kind = 'hog_flow'
                AND function_id IN %(workflow_ids)s AND scheduled_at >= %(after)s
                AND (function_id, invocation_id) IN candidates
            GROUP BY function_id, invocation_id
        ), if(startsWith(latest.7, '{{'), latest.7,
            decompress(base64Decode(if(startsWith(latest.7, 'H4sI'), latest.7, %(empty_context)s)), 'gzip')) AS context,
        JSONExtractString(context, 'event', 'event') AS trigger_event,
        JSONExtractString(context, 'event', 'properties', 'account_id') AS stored_account_id
        SELECT function_id, invocation_id, latest.1 AS status,
            latest.2 AS triggered_at, latest.5 AS parent_run_id
        FROM latest_runs
        WHERE latest.3 = 0 AND (
            (startsWith(trigger_event, '$account_') AND (
                stored_account_id = %(account_id)s
                OR (stored_account_id = '' AND (
                    JSONExtractString(context, 'event', 'distinct_id') = %(account_identity)s
                    OR (%(has_external_id)s AND JSONExtractString(context, 'event', 'properties', 'account_external_id') = %(external_id)s)
                ))
            ))
            OR (JSONExtractBool(context, 'accountAudience') AND trigger_event = '$batch_hog_flow_invocation'
                AND %(has_external_id)s AND latest.6 = %(external_id)s)
            OR latest.4 GLOBAL IN ({event_query})
        )"""
    return AccountRunsQuery(
        count_sql=f"SELECT count() FROM ({sql})",
        page_sql=f"{sql} ORDER BY triggered_at DESC, invocation_id DESC, function_id DESC LIMIT %(limit)s OFFSET %(offset)s",
        parameters={
            **context.values,
            "team_id": team.pk,
            "workflow_ids": list(workflow_ids),
            "after": after,
            "account_id": account_id,
            "account_identity": f"account:{account_id}",
            "identities": [f"account:{account_id}"] + ([external_id] if external_id is not None else []),
            "external_id": external_id or "",
            "has_external_id": external_id is not None,
            "empty_context": base64.b64encode(gzip.compress(b"{}")).decode(),
        },
    )


def get_workflow_steps(
    *, team: Team, workflow_ids: set[str], user_access_control: "UserAccessControl"
) -> dict[str, list[WorkflowStep]]:
    if not workflow_ids:
        return {}
    if not (settings.DEBUG or settings.TEST) and not all(
        (
            settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST,
            settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT,
            settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE,
            settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_USER,
            settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD,
        )
    ):
        steps = {}
        for workflow_id in workflow_ids:
            try:
                workflow = get_workflow(
                    team_id=team.pk,
                    workflow_id=workflow_id,
                    user_access_control=user_access_control,
                    required_level="viewer",
                )
            except (WorkflowNotFound, WorkflowAccessDenied):
                continue
            steps[workflow_id] = [
                WorkflowStep(action_id=action["id"], action_type=action["type"], name=action.get("name") or "")
                for action in workflow.actions
                if isinstance(action, dict)
                and isinstance(action.get("id"), str)
                and isinstance(action.get("type"), str)
            ]
        return steps
    response = execute_hogql_query(
        """SELECT id, arrayMap(action -> tuple(JSONExtractString(action, 'id'),
            JSONExtractString(action, 'type'), JSONExtractString(action, 'name')),
            JSONExtractArrayRaw(actions)) FROM system.hog_flows WHERE id IN {workflow_ids} LIMIT {limit}""",
        team=team,
        placeholders={
            "workflow_ids": ast.Constant(value=list(workflow_ids)),
            "limit": ast.Constant(value=len(workflow_ids)),
        },
        user=user_access_control.user,
        user_access_control=user_access_control,
        workload=Workload.ONLINE,
    )
    return {
        str(workflow_id): [
            WorkflowStep(action_id=action_id, action_type=action_type, name=name)
            for action_id, action_type, name in actions
        ]
        for workflow_id, actions in response.results or []
    }


def list_account_runs(
    *,
    team: Team,
    account_id: str,
    external_id: str | None,
    workflow_ids: set[str],
    user_access_control: "UserAccessControl",
    page: PageRequest,
) -> Page[AccountAutomation]:
    tag_queries(product=ProductKey.CUSTOMER_ANALYTICS, feature=Feature.QUERY)
    names = get_workflow_names(team_id=team.pk, workflow_ids=workflow_ids)
    if not names:
        return Page(results=[], count=0)
    query = get_account_runs_query(team=team, account_id=account_id, external_id=external_id, workflow_ids=set(names))
    count = sync_execute(
        query.count_sql,
        query.parameters,
        workload=Workload.ONLINE,
        team_id=team.pk,
    )[0][0]
    if not count or page.offset >= count:
        return Page(results=[], count=count)
    rows = sync_execute(
        query.page_sql,
        {**query.parameters, "limit": page.limit, "offset": page.offset},
        workload=Workload.ONLINE,
        team_id=team.pk,
    )
    runs: list[AccountAutomation] = []
    log_sources: dict[tuple[str, str], str] = {}
    for workflow_id, invocation_id, status, triggered_at, parent_run_id in rows:
        run_key = (workflow_id, invocation_id)
        log_sources[run_key] = parent_run_id or workflow_id
        runs.append(
            AccountAutomation(
                workflow_id=workflow_id,
                workflow_name=names[workflow_id],
                invocation_id=invocation_id,
                status=status,
                triggered_at=triggered_at.replace(tzinfo=UTC),
                last_completed_step_at=None,
                expected_resume_at=None,
            )
        )

    selected = runs
    if not selected:
        return Page(results=[], count=count)
    logs = sync_execute(
        """SELECT log_source_id, instance_id, timestamp,
            if(match(message, %(failure_pattern)s), %(failure_evidence)s, left(message, 256)) AS evidence
        FROM log_entries
        WHERE team_id = %(team_id)s AND log_source = 'hog_flow'
            AND (log_source_id, instance_id) IN %(run_keys)s
            AND timestamp >= %(after)s
            AND (startsWith(message, 'Executing action ') OR startsWith(message, 'Workflow moved to action ')
                OR startsWith(message, 'Workflow will pause until ') OR message = 'Workflow completed'
                OR match(message, %(failure_pattern)s))
        ORDER BY timestamp DESC, evidence DESC
        LIMIT %(log_limit)s BY log_source_id, instance_id""",
        {
            "team_id": team.pk,
            "run_keys": [(log_sources[(r.workflow_id, r.invocation_id)], r.invocation_id) for r in selected],
            "after": timezone.now() - timedelta(days=90),
            "log_limit": MAX_RUN_LOG_ENTRIES + 1,
            "failure_pattern": WORKFLOW_FAILURE_PATTERN,
            "failure_evidence": WORKFLOW_FAILURE_EVIDENCE,
        },
        workload=Workload.ONLINE,
        team_id=team.pk,
    )
    by_run: dict[tuple[str, str], list[tuple[datetime, str]]] = {}
    for workflow_id, invocation_id, timestamp, message in logs:
        by_run.setdefault((workflow_id, invocation_id), []).append((timestamp.replace(tzinfo=UTC), message))
    results = []
    workflows = get_workflow_steps(
        team=team, workflow_ids={run.workflow_id for run in selected}, user_access_control=user_access_control
    )
    for run in selected:
        actions = workflows.get(run.workflow_id, [])
        run_logs = by_run.get((log_sources[(run.workflow_id, run.invocation_id)], run.invocation_id), [])
        if len(run_logs) > MAX_RUN_LOG_ENTRIES:
            results.append(run)
            continue
        run_logs.reverse()
        completed_step = get_last_completed_step(
            run_logs,
            exit_action_ids={action.action_id for action in actions if action.action_type == "exit"},
        )
        step_name = next(
            (action.name for action in actions if completed_step and action.action_id == completed_step.action_id),
            None,
        )
        results.append(
            replace(
                run,
                last_completed_step_at=completed_step.completed_at if completed_step else None,
                last_completed_step_name=step_name or None,
                expected_resume_at=(
                    get_expected_resume_at(
                        run_logs,
                        now=timezone.now(),
                        delay_action_ids={
                            action.action_id for action in actions if action.action_type in {"delay", "delay_until"}
                        },
                    )
                    if run.status == "running"
                    else None
                ),
            )
        )
    return Page(results=results, count=count)
