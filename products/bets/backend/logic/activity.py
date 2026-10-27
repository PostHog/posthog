from datetime import datetime
from typing import TYPE_CHECKING, TypedDict

from django.db.models import Max, Sum

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog, apply_activity_visibility_restrictions
from posthog.models.activity_logging.retention import get_activity_log_lookback_restriction

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.facade import api as experiments
from products.signals.backend.facade import api as signals
from products.tasks.backend.facade import api as tasks

from ..db import WRITER_DB
from ..models import Bet, LedgerEntry, WorkItem

if TYPE_CHECKING:
    from products.tasks.backend.facade.contracts import TaskDetailDTO


class ActivityEntry(TypedDict):
    id: str
    at: datetime
    title: str
    detail: str
    resource: str
    resource_id: str


def recent_activity(team: Team, user: User, bet: Bet) -> list[ActivityEntry]:
    events: list[ActivityEntry] = []
    visible_tasks: dict[str, TaskDetailDTO] = {}

    def add(
        key: str, at: datetime | None, title: str, detail: str = "", resource: str = "", resource_id: str = ""
    ) -> None:
        if at:
            events.append(
                ActivityEntry(id=key, at=at, title=title, detail=detail, resource=resource, resource_id=resource_id)
            )

    add(f"bet:{bet.id}", bet.created_at, "Bet created", bet.title)
    for work in WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet):
        native = tasks.get_task_detail(work.task_id, bet.team_id, user.id) if work.task_id else None
        if native:
            visible_tasks[str(work.id)] = native
            add(f"task:{work.task_id}", native.created_at, "Task prepared", native.title, "task", str(work.task_id))
            for run in tasks.list_task_runs(native.id, bet.team_id, user_id=user.id):
                add(f"run:{run.id}", run.created_at, "Task run created", native.title, "task", str(work.task_id))
                if run.status in ("completed", "failed", "cancelled"):
                    add(
                        f"finished:{run.id}",
                        run.completed_at,
                        f"Task {run.status}",
                        native.title,
                        "task",
                        str(work.task_id),
                    )
        if work.finished_at:
            add(
                f"finished:{work.id}",
                work.finished_at,
                {
                    "done": "Tracking checked" if work.kind == "tracking" else "Idea learned",
                    "dropped": "Idea dropped",
                }.get(work.stage, "Work finished"),
                f"{work.title}. {work.note}".strip(),
                "experiment" if work.experiment_id else "task" if native else "",
                str(work.experiment_id or (work.task_id if native else "")),
            )
        if work.merged_at:
            add(f"merged:{work.id}", work.merged_at, "Pull request merged", work.title, "pull_request", work.pr_url)
    work_task_ids = {str(task.id) for task in visible_tasks.values()}
    for run_id in signals.scout_run_ids_for_source(
        bet.team_id, "bets", [f"{bet.id}:v{version}" for version in range(1, bet.goal_version + 1)]
    ):
        scout_run = tasks.get_task_run(run_id, team_id=bet.team_id)
        if scout_run is None or str(scout_run.task_id) in work_task_ids:
            continue
        scout_task = tasks.get_task_detail(scout_run.task_id, bet.team_id, user.id)
        if scout_task is None:
            continue
        add(
            f"run:{scout_run.id}",
            scout_run.created_at,
            "Scout run started",
            bet.title,
            "task",
            str(scout_task.id),
        )
        if scout_run.is_terminal:
            add(
                f"finished:{scout_run.id}",
                scout_run.completed_at,
                f"Scout {scout_run.status}",
                scout_run.error_message or bet.title,
                "task",
                str(scout_task.id),
            )
    for entry in (
        LedgerEntry.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, kind__in=["allocate", "deallocate"])
        .order_by("-created_at")[:200]
    ):
        add(
            f"budget:{entry.id}",
            entry.created_at,
            {"allocate": "Budget allocated", "deallocate": "Budget returned"}[entry.kind],
            f"${entry.amount_cents / 100:,.2f}",
        )
    for usage in (
        LedgerEntry.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, kind="spend")
        .values("work_item_id")
        .annotate(total_cents=Sum("amount_cents"), at=Max("created_at"))
        .order_by("-at")[:200]
    ):
        native = visible_tasks.get(str(usage["work_item_id"]))
        add(
            f"usage:{bet.id}:{usage['work_item_id'] or 'unassigned'}",
            usage["at"],
            "Task usage recorded" if native else "Usage recorded",
            f"${usage['total_cents'] / 100:,.2f}" + (f" · {native.title}" if native else ""),
            "task" if native else "",
            str(native.id) if native else "",
        )
    access = UserAccessControl(user=user, team=team)
    if access.check_access_level_for_resource("activity_log", "viewer"):
        rows = apply_activity_visibility_restrictions(
            ActivityLog.objects.filter(team_id=bet.team_id, scope="Bet", item_id=str(bet.id)).exclude(
                activity="created"
            ),
            user,
        )
        since = get_activity_log_lookback_restriction(team.organization)
        if since:
            rows = rows.filter(created_at__gte=since)
        for row in rows.order_by("-created_at")[:200]:
            changes = (row.safe_detail or {}).get("changes") or []
            status = next((change for change in changes if change.get("field") == "status"), None)
            title = f"Bet {row.activity}"
            if status:
                title = {
                    "running": "Bet running",
                    "paused": "Bet paused",
                    "reached": "Goal reached",
                    "spent": "Budget used",
                    "closed": "Bet closed",
                    "setting_up": "Goal updated",
                }.get(str(status.get("after")), title)
            elif any(change.get("field") == "scout_config_id" and change.get("after") for change in changes):
                title = "Scout connected"
            field_labels = {
                "title": "Name",
                "statement": "Belief",
                "audience": "Audience",
                "area": "Product area",
                "repository": "Repository",
                "goal_insight": "Primary metric insight",
                "goal_metric": "Primary metric",
                "secondary_metrics": "Secondary metrics",
                "target": "Target",
                "unit": "Metric unit",
                "direction": "Goal direction",
            }
            add(
                str(row.id),
                row.created_at,
                title,
                ", ".join(field_labels[field] for change in changes if (field := change.get("field")) in field_labels),
            )
    ids = [
        experiment_id
        for experiment_id in WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, experiment_id__isnull=False)
        .values_list("experiment_id", flat=True)
        if experiment_id is not None
    ]
    for event in experiments.activity_for_experiments(team=team, user=user, experiment_ids=ids, limit=200):
        label = "Experiment" if event.scope == "Experiment" else "Feature flag"
        action = event.activity
        for change in event.changes or []:
            if change.get("field") == "active" and isinstance(change.get("after"), bool):
                action = "enabled" if change["after"] else "disabled"
            elif change.get("field") in ("start_date", "end_date") and change.get("after"):
                action = "started" if change["field"] == "start_date" else "ended"
        add(
            event.id,
            event.at,
            f"{label} {action}",
            event.name,
            "experiment" if event.scope == "Experiment" else "flag",
            event.item_id,
        )
    return sorted(events, key=lambda entry: (entry["at"], entry["id"]), reverse=True)[:200]
