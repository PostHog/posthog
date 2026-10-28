import re
import math
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from statistics import fmean
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

import structlog
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request

from posthog.models import Team, User

from products.experiments.backend.facade import api as experiments
from products.experiments.backend.facade.coordination import (
    cleanup_task_id,
    conclude,
    evidence as experiment_evidence,
    ship,
)
from products.signals.backend.facade import api as signals
from products.tasks.backend.facade import api as tasks
from products.tasks.backend.facade.cancellation import cancel_task_run
from products.tasks.backend.facade.contracts import TaskRunDTO
from products.tasks.backend.facade.usage import task_run_usage_limited

from ..db import WRITER_DB
from ..facade.enums import (
    BetStatus,
    EvidenceKind,
    IdeaAssessment,
    IdeaOutcome,
    IdeaSource,
    LedgerKind,
    ModelStep,
    WorkKind,
    WorkStage,
)
from ..models import Bet, LedgerEntry, WorkItem
from . import access
from .baseline import baseline
from .ledger import append, totals
from .metrics import metric, proposed_plan, refresh_metrics, validate_goal
from .notify import notify_owner
from .plan import (
    DRIFT,
    EXPOSURE_GRACE,
    MIN_DAYS,
    MIN_OBSERVATIONS,
    control_spread,
    plan as make_plan,
)
from .prompts import instructions
from .scout import scout_body, scout_failure, scout_job
from .spend import reconcile_spend, spend_pending
from .step_models import run_settings
from .usage import track_from_task
from .verdict import Verdict, verdict
from .workspace import get_settings

logger = structlog.get_logger(__name__)

RUN_BUDGET_CENTS = 500
BUILD_MINUTES = 60
MAX_ATTEMPTS = 3
MAX_EVIDENCE = 8
IDEA_REPORT_STATUSES = ("ready", "pending_input")
LEASE = timedelta(minutes=10)
HARM_CONFIRM = timedelta(hours=12)
GOAL_POINTS = 3
OPEN = (WorkStage.WORKING, WorkStage.REVIEW, WorkStage.LIVE)
OWNER_TITLE = re.compile(r"^\s*(?:bet idea:\s*)?owner idea (\d+)\s*[:.\-]\s*", re.IGNORECASE)
VERDICT = re.compile(r"^\W*(not supported|supported)\b", re.IGNORECASE)
AUDIENCE = re.compile(r"^\W*audience\W*:\D*([\d,]+)", re.IGNORECASE | re.MULTILINE)
METRIC = re.compile(r"^\W*metric\W*:\s*(.+?)\W*$", re.IGNORECASE | re.MULTILINE)
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
EVIDENCE_KINDS = (
    ("/replay/", EvidenceKind.REPLAY),
    ("session_recording", EvidenceKind.REPLAY),
    ("/insights/", EvidenceKind.INSIGHT),
    ("/experiments/", EvidenceKind.EXPERIMENT),
    ("/error_tracking/", EvidenceKind.ERROR),
)
ACTIVE_RUN = ("queued", "in_progress")
INSIGHT_LINE = re.compile(r"Insight:\s*`?([A-Za-z0-9]{8})\b")
CONCLUSIONS = {
    IdeaOutcome.WON: "won",
    IdeaOutcome.LOST: "lost",
    IdeaOutcome.FLAT: "inconclusive",
    IdeaOutcome.HARMED: "stopped_early",
    IdeaOutcome.DROPPED: "stopped_early",
}


def items(bet: Bet) -> QuerySet[WorkItem]:
    return WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet, goal_version=bet.goal_version)


def move(work: WorkItem, stage: WorkStage, note: str = "", **fields: object) -> None:
    work.stage = stage
    work.note = note
    for name, value in fields.items():
        setattr(work, name, value)
    if stage in (WorkStage.DONE, WorkStage.DROPPED) and work.finished_at is None:
        work.finished_at = timezone.now()
    work.save(using=WRITER_DB)


def create_work(bet: Bet, owner: User, *, kind: WorkKind, key: str, title: str, **fields: object) -> WorkItem:
    work, _ = (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .get_or_create(
            team_id=bet.team_id,
            bet=bet,
            key=key,
            defaults={"kind": kind, "title": title[:255], "goal_version": bet.goal_version, **fields},
        )
    )
    return ensure_task(bet, owner, work)


def ensure_task(bet: Bet, owner: User, work: WorkItem) -> WorkItem:
    if work.task_id is None:
        origin_key = f"bets:{work.id}"
        existing = tasks.get_task_by_origin_key(bet.team_id, origin_key)
        work.task_id = (
            existing.id
            if existing
            else tasks.create_task_without_run(
                team=Team.objects.get(id=bet.team_id),
                user_id=owner.id,
                title=work.title,
                description=instructions(bet, work),
                repository=bet.repository,
                repositories=bet.repos,
                origin_product=tasks.TaskOriginProduct.BETS,
                origin_key=origin_key,
            )
        )
        work.save(using=WRITER_DB, update_fields=["task_id", "updated_at"])
    return work


def pull_request(work: WorkItem) -> tuple[str, str]:
    if work.task_id is None:
        return ("", "")
    prs = tasks.get_pull_requests_for_tasks(work.team_id, [work.task_id]).get(str(work.task_id), [])
    return (prs[0].url, prs[0].state) if prs else ("", "")


def turn_finished(run_id: UUID, task_id: UUID, team_id: int) -> bool:
    log = tasks.read_task_run_logs(run_id, task_id, team_id) or ""
    return log.rfind('"stopReason"') > log.rfind('"session/prompt"') >= 0


def reported_insight(work: WorkItem) -> str:
    if work.task_run_id is None or work.task_id is None:
        return ""
    log = tasks.read_task_run_logs(work.task_run_id, work.task_id, work.team_id) or ""
    found = INSIGHT_LINE.findall(log.replace("\\n", "\n"))
    return found[-1] if found else ""


def adopt_insight(team: Team, user: User, bet: Bet, work: WorkItem) -> bool:
    short_id = reported_insight(work)
    try:
        if not short_id:
            raise ValidationError("missing")
        validate_goal(team, user, short_id)
    except ValidationError:
        stop_idle_run(work, bet)
        move(
            work,
            WorkStage.WORKING,
            "End your last message with the line Insight: <short id> for the saved insight that measures the goal.",
            task_run_id=None,
        )
        return False
    bet.goal_insight = short_id
    bet.goal_metric = (metric(team, user, short_id).name or bet.goal_metric)[:255]
    bet.save(using=WRITER_DB, update_fields=["goal_insight", "goal_metric", "updated_at"])
    return True


def run_state(work: WorkItem) -> tuple[str, str]:
    run = tasks.get_task_run(work.task_run_id, team_id=work.team_id) if work.task_run_id else None
    if run is None:
        return ("", "")
    if run.status in ACTIVE_RUN and turn_finished(run.id, run.task_id, work.team_id):
        return ("idle", "")
    return (run.status, run.error_message or "")


def stop_idle_run(work: WorkItem, bet: Bet) -> None:
    run = tasks.get_task_run(work.task_run_id, team_id=work.team_id) if work.task_run_id else None
    if run and run.status in ACTIVE_RUN:
        cancel_task_run(
            run.id,
            run.task_id,
            bet.team_id,
            reason="The task finished its work.",
            source="bets",
            requested_by_user_id=bet.owner_id,
        )


def observe(team: Team, user: User, bet: Bet, work: WorkItem) -> None:
    url, state = pull_request(work)
    status, error = run_state(work)
    if work.stage == WorkStage.WORKING:
        if work.kind == WorkKind.TRACKING and not bet.goal_insight:
            if status not in ("completed", "idle"):
                if status in ("failed", "cancelled"):
                    stop_idle_run(work, bet)
                    move(
                        work,
                        WorkStage.WORKING,
                        error or "The task ended without finding the insight.",
                        task_run_id=None,
                    )
                return
            if not adopt_insight(team, user, bet, work):
                return
        if url:
            work.pr_url = url
        elif status in ("completed", "idle") and work.kind == WorkKind.TRACKING:
            stop_idle_run(work, bet)
            move(work, WorkStage.DONE, "Tracking already measures the goal.")
            return
        elif status in ("completed", "idle", "failed", "cancelled"):
            stop_idle_run(work, bet)
            move(work, WorkStage.WORKING, error or "The task ended without a pull request.", task_run_id=None)
            return
        else:
            return
        if work.kind == WorkKind.IDEA:
            experiment = experiments.experiment_for_read(team=team, user=user, feature_flag_key=work.flag_key)
            if experiment is None:
                if status in ACTIVE_RUN:
                    return
                stop_idle_run(work, bet)
                move(
                    work,
                    WorkStage.WORKING,
                    f"Create and launch the experiment for the flag {work.flag_key}.",
                    task_run_id=None,
                )
                return
            work.experiment_id = experiment.id
        move(work, WorkStage.REVIEW, "Waiting for review.")
        return
    if work.stage == WorkStage.REVIEW:
        if state == "merged":
            if work.kind != WorkKind.IDEA:
                move(work, WorkStage.DONE, "Merged.", merged_at=timezone.now())
            else:
                move(work, WorkStage.LIVE, "Waiting for the first people to see it.", merged_at=timezone.now())
        elif state == "closed":
            if work.kind != WorkKind.IDEA:
                move(work, WorkStage.STUCK, "The pull request was closed. Retry to open a new one.")
            else:
                move(work, WorkStage.DROPPED, "The pull request was closed.", result={"outcome": IdeaOutcome.DROPPED})
                end_experiment(bet, work)
        return
    if work.stage == WorkStage.LIVE and work.experiment_id:
        try:
            data = experiment_evidence(team=team, user=user, experiment_id=work.experiment_id)
        except PermissionDenied:
            move(work, WorkStage.STUCK, "The experiment is gone or the owner cannot edit it.")
            return
        planned = replan(team, user, bet, work, data)
        exposed_at = planned.get("exposed_at")
        result = verdict(
            data,
            direction=bet.direction,
            guardrails=bet.secondary_metrics,
            run_days=planned["days"],
            exposed_at=datetime.fromisoformat(exposed_at) if exposed_at else None,
        )
        result = confirm_harm(work, result)
        note = result.note
        if not result.facts.get("exposures") and work.merged_at and timezone.now() - work.merged_at > EXPOSURE_GRACE:
            note = "No exposures since the merge. Check that the change is deployed."
        if result.outcome is None or (planned.get("proposed_days") and result.outcome != IdeaOutcome.HARMED):
            if planned.get("proposed_days") and result.outcome is not None:
                note = extend_question(planned)
            move(work, WorkStage.LIVE, note, result={**work.result, **result.facts}, plan=planned)
            return
        comment = f"Concluded by bet {bet.reference}: {result.note}"
        try:
            ship(
                team=team,
                user=user,
                experiment_id=work.experiment_id,
                variant=result.variant if result.outcome == IdeaOutcome.WON and result.variant else "control",
                conclusion=CONCLUSIONS[result.outcome],
                comment=comment,
                repository=bet.repository,
            )
        except (PermissionDenied, ValidationError) as error:
            logger.warning("bets.ship_failed", bet_id=str(bet.id), error=str(error))
            try:
                conclude(
                    team=team,
                    user=user,
                    experiment_id=work.experiment_id,
                    conclusion=CONCLUSIONS[result.outcome],
                    comment=comment,
                    repository=bet.repository,
                )
            except PermissionDenied:
                move(work, WorkStage.STUCK, "Bets could not end the experiment. The owner cannot edit it.")
                return
        move(
            work,
            WorkStage.DONE,
            result.note,
            result={**result.facts, "outcome": result.outcome, "variant": result.variant, "verdict": result.note},
            plan=planned,
        )
        track_from_task(
            team,
            user,
            "bet idea concluded",
            {
                "bet_id": str(bet.id),
                "work_id": str(work.id),
                "outcome": result.outcome,
                "planned_days": planned.get("days"),
                "replanned": bool(planned.get("replanned")),
                "owner_idea": work.source == IdeaSource.OWNER,
            },
        )
        follow_cleanup(team, user, bet, work)


def confirm_harm(work: WorkItem, result: Verdict) -> Verdict:
    seen = work.result.get("harm_seen_at")
    if result.outcome != IdeaOutcome.HARMED:
        return replace(result, facts={**result.facts, "harm_seen_at": None}) if seen else result
    if seen and timezone.now() - datetime.fromisoformat(seen) >= HARM_CONFIRM:
        return result
    first = seen or timezone.now().isoformat()
    hours = int(HARM_CONFIRM.total_seconds() // 3600)
    return Verdict(
        outcome=None,
        variant="",
        note=f"{result.note} Bets checks again within {hours} hours before it stops the experiment.",
        facts={**result.facts, "harm_seen_at": first},
    )


def end_experiment(bet: Bet, work: WorkItem) -> None:
    owner = User.objects.filter(id=bet.owner_id).first()
    if not work.experiment_id or owner is None:
        return
    try:
        conclude(
            team=Team.objects.get(id=bet.team_id),
            user=owner,
            experiment_id=work.experiment_id,
            conclusion="stopped_early",
            comment=f"Stopped by bet {bet.reference}: {work.note}",
            repository=bet.repository,
        )
    except PermissionDenied:
        logger.warning("bets.end_experiment_failed", bet_id=str(bet.id), work_id=str(work.id))


def extend_question(planned: dict) -> str:
    extra = planned["proposed_days"] - planned["days"]
    return f"The traffic is lower than planned. It needs {extra} more days. Extend or stop?"


def replan(team: Team, user: User, bet: Bet, work: WorkItem, data: dict) -> dict:
    settings = get_settings(bet.team_id)
    planned = dict(work.plan)
    if not planned.get("days"):
        proposal = proposed_plan(
            team,
            user,
            bet.goal_insight,
            audience=planned.get("audience"),
            mde=settings.mde_percent,
            floor_days=math.ceil(settings.min_run_hours / 24),
        )
        planned = {
            **planned,
            **(asdict(proposal[0]) if proposal and proposal[0] else {"days": MIN_DAYS, "mde": settings.mde_percent}),
        }
    results = data.get("results") or {}
    exposed = sum((results.get("exposures") or {}).values())
    if exposed > 0 and not planned.get("exposed_at"):
        planned["exposed_at"] = timezone.now().isoformat()
    baselines = results.get("metric_baselines") or []
    spread = control_spread(baselines[0]) if baselines else None
    if planned.get("replanned") or not planned.get("exposed_at") or spread is None:
        return planned
    elapsed = (timezone.now() - datetime.fromisoformat(planned["exposed_at"])).total_seconds() / 86400
    if elapsed < MIN_DAYS or baselines[0].get("number_of_samples", 0) < MIN_OBSERVATIONS:
        return planned
    audience = round(exposed / elapsed)
    fresh = make_plan(
        spread,
        mde=float(planned["mde"]),
        audience=audience,
        weekly=bool(planned.get("weekly")),
        floor_days=math.ceil(settings.min_run_hours / 24),
    )
    planned["replanned"] = True
    planned["audience"] = audience
    if fresh.days > planned["days"] * DRIFT:
        planned["proposed_days"] = fresh.days
    else:
        planned["days"] = max(planned["days"], fresh.days)
    return planned


def follow_cleanup(team: Team, user: User, bet: Bet, idea: WorkItem) -> None:
    task_id = cleanup_task_id(team=team, experiment_id=idea.experiment_id) if idea.experiment_id else None
    if task_id is None:
        return
    runs = tasks.get_latest_run_by_task([str(task_id)])
    run = runs.get(str(task_id))
    WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).get_or_create(
        team_id=bet.team_id,
        bet=bet,
        key=f"cleanup:{idea.id}",
        defaults={
            "kind": WorkKind.CLEANUP,
            "stage": WorkStage.WORKING,
            "title": f"Remove the flag {idea.flag_key}",
            "note": "Removing the flag from the code.",
            "task_id": task_id,
            "task_run_id": run.id if run else None,
            "flag_key": idea.flag_key,
            "goal_version": bet.goal_version,
        },
    )


def goal_reached(team: Team, user: User, bet: Bet) -> bool:
    refresh_metrics(team, user, [bet.goal_insight])
    values = metric(team, user, bet.goal_insight).values[-GOAL_POINTS:]
    if not values or bet.target is None:
        return False
    current = fmean(values)
    return current <= float(bet.target) if bet.direction == "decrease" else current >= float(bet.target)


def goal_check(team: Team, user: User, bet: Bet, idea_open: bool) -> tuple[bool, str]:
    met = goal_reached(team, user, bet)
    since = (bet.goal_met_since or timezone.now()) if met else None
    if since != bet.goal_met_since:
        bet.goal_met_since = since
        bet.save(using=WRITER_DB, update_fields=["goal_met_since", "updated_at"])
    if since is None:
        return (False, "")
    confirm = timedelta(hours=get_settings(bet.team_id).goal_confirm_hours)
    if timezone.now() - since < confirm:
        hours = int(confirm.total_seconds() // 3600)
        return (False, f"The goal is at the target. Bets confirms it for {hours} hours.")
    if idea_open:
        return (False, "The goal is at the target. The bet ends when the current idea has a result.")
    return (True, "")


def clean_title(title: str) -> str:
    title = re.sub(r"^bet idea:\s*", "", title, flags=re.IGNORECASE)
    return title[:1].upper() + title[1:]


def source_id(bet: Bet) -> str:
    return f"{bet.id}:v{bet.goal_version}"


def evidence_from(summary: str) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for label, url in LINK.findall(summary):
        kind = (
            EvidenceKind.CHART
            if url.startswith("chart:")
            else next((kind for marker, kind in EVIDENCE_KINDS if marker in url), EvidenceKind.LINK)
        )
        found.setdefault(url, {"kind": kind.value, "label": label.strip()[:200], "url": url})
    return list(found.values())[:MAX_EVIDENCE]


def ingest(bet: Bet) -> int:
    linked = {str(report) for report in items(bet).exclude(report_id=None).values_list("report_id", flat=True)}
    added = 0
    for report in sorted(
        signals.scout_reports_for_source(bet.team_id, "bets", source_id(bet)), key=lambda report: report.filed_at
    ):
        if report.status not in IDEA_REPORT_STATUSES or report.report_id in linked:
            continue
        if bet.baseline_at and report.filed_at < bet.baseline_at:
            continue
        evidence = evidence_from(report.summary)
        metric_match = METRIC.search(report.summary)
        moves_metric = metric_match.group(1).strip("* ")[:255] if metric_match else ""
        audience_match = AUDIENCE.search(report.summary)
        audience = {"audience": int(audience_match.group(1).replace(",", ""))} if audience_match else {}
        owner = OWNER_TITLE.match(report.title)
        target = (
            items(bet).filter(key=f"owner:{owner.group(1)}", stage=WorkStage.PROPOSED, report_id=None).first()
            if owner
            else None
        )
        if owner and target is None:
            linked.add(report.report_id)
            continue
        if target:
            verdict_match = VERDICT.match(report.summary.strip())
            target.report_id = report.report_id
            target.summary = report.summary
            target.evidence = evidence
            target.moves_metric = moves_metric
            target.plan = {**target.plan, **audience}
            target.assessment = (
                IdeaAssessment.NOT_SUPPORTED
                if verdict_match and verdict_match.group(1).lower() == "not supported"
                else IdeaAssessment.SUPPORTED
                if verdict_match
                else IdeaAssessment.PENDING
            )
            target.save(using=WRITER_DB)
        else:
            WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).get_or_create(
                team_id=bet.team_id,
                bet=bet,
                key=f"report:{report.report_id}",
                defaults={
                    "kind": WorkKind.IDEA,
                    "stage": WorkStage.PROPOSED,
                    "source": IdeaSource.SCOUT,
                    "assessment": IdeaAssessment.SUPPORTED,
                    "title": clean_title(OWNER_TITLE.sub("", report.title))[:255],
                    "summary": report.summary,
                    "report_id": report.report_id,
                    "evidence": evidence,
                    "moves_metric": moves_metric,
                    "plan": audience,
                    "goal_version": bet.goal_version,
                },
            )
        linked.add(report.report_id)
        added += 1
    return added


def add_owner_idea(bet: Bet, title: str) -> WorkItem:
    keys = items(bet).filter(source=IdeaSource.OWNER).values_list("key", flat=True)
    number = (
        max((int(key.removeprefix("owner:")) for key in keys if key.removeprefix("owner:").isdecimal()), default=0) + 1
    )
    return (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .create(
            team_id=bet.team_id,
            bet=bet,
            key=f"owner:{number}",
            kind=WorkKind.IDEA,
            stage=WorkStage.PROPOSED,
            source=IdeaSource.OWNER,
            assessment=IdeaAssessment.PENDING,
            title=title.strip()[:255],
            goal_version=bet.goal_version,
        )
    )


def set_scout(bet: Bet, enabled: bool) -> None:
    if bet.scout_config_id:
        signals.update_scout_for_source(bet.team_id, "bets", str(bet.scout_config_id), enabled=enabled)


def run_scout(team: Team, user: User, bet: Bet, reason: str) -> str:
    try:
        model = run_settings(get_settings(bet.team_id), user, ModelStep.SCOUT).get("model")
    except ValueError:
        model = None
    if not signals.scouts_for_source(bet.team_id, "bets", source_id(bet)):
        request = Request(HttpRequest())
        request.user = user
        created = signals.create_scout_for_source(
            team=team,
            user=user,
            name=f"bet-{bet.reference}-v{bet.goal_version}",
            display_name=bet.title,
            description=f"Find the next idea to improve {bet.goal_metric}.",
            body=scout_body(bet),
            files=[],
            config_options={
                "enabled": True,
                "emit": True,
                "output_destinations": {"inbox": False},
                "repositories": bet.repos,
                **({"model": model} if model else {}),
            },
            request=request,
            serializer_context={"project_id": team.project_id, "team": team, "request": request},
            source_product="bets",
            source_id=source_id(bet),
        )
        bet.scout_config_id = created.config.id
        bet.save(using=WRITER_DB, update_fields=["scout_config_id", "updated_at"])
    signals.update_scout_for_source(bet.team_id, "bets", str(bet.scout_config_id), enabled=True, model=model or "")
    try:
        signals.run_scout_for_source(bet.team_id, "bets", str(bet.scout_config_id))
    except signals.WorkflowScoutRunRejected as error:
        if error.rejection.kind not in (
            signals.ScoutRunRejectionKind.CONFLICT,
            signals.ScoutRunRejectionKind.THROTTLED,
        ):
            return f"The Scout cannot run: {error.rejection.detail}"
    except ValueError as error:
        return f"The Scout cannot run: {error}"
    return reason


def dispatch(bet: Bet, user: User) -> str:
    note = dispatch_lane(bet, user, [WorkKind.TRACKING, WorkKind.IDEA])
    dispatch_lane(bet, user, [WorkKind.CLEANUP])
    return note


def dispatch_lane(bet: Bet, user: User, kinds: list[WorkKind]) -> str:
    building = list(items(bet).filter(stage=WorkStage.WORKING, kind__in=kinds).order_by("created_at"))
    runs = tasks.get_latest_run_by_task([str(work.task_id) for work in building if work.task_id])
    if any(run.status in ACTIVE_RUN for run in runs.values()):
        return ""
    work = next((work for work in building if work.task_run_id is None and work.task_id), None)
    if work is None or work.task_id is None:
        return ""
    if work.attempts >= MAX_ATTEMPTS:
        move(work, WorkStage.STUCK, work.note or "The task did not finish after three attempts.")
        return "This step needs attention."
    if spend_pending(bet, work):
        return "Waiting for task usage to settle."
    if task_run_usage_limited(user, bet.team_id):
        return "The project's task usage limit is reached."
    amount = min(RUN_BUDGET_CENTS, totals(bet.team_id, bet).available_cents)
    if amount <= 0:
        return "The budget is used up. Add budget to continue."
    settings = get_settings(bet.team_id)
    try:
        model = run_settings(settings, user, ModelStep.IDEA if work.kind == WorkKind.IDEA else ModelStep.TRACKING)
    except ValueError as error:
        return str(error)
    reservations = (
        LedgerEntry.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(work_item=work, kind=LedgerKind.RESERVE)
        .count()
    )
    if held := totals(bet.team_id, work=work).reserved_cents:
        append(settings, bet, LedgerKind.RELEASE, held, f"stale:{work.id}:{reservations}", work=work)
    append(settings, bet, LedgerKind.RESERVE, amount, f"run:{work.id}:{reservations + 1}", work=work)
    work.attempts += 1
    work.save(using=WRITER_DB, update_fields=["attempts", "updated_at"])
    if work.kind != WorkKind.CLEANUP:
        tasks.update_task(work.task_id, bet.team_id, user.id, validated_data={"description": instructions(bet, work)})
    result = tasks.run_task(
        work.task_id,
        bet.team_id,
        user.id,
        validated_data={
            "mode": "background",
            "run_source": "manual",
            **model,
            "pr_authorship_mode": "bot",
            "auto_publish": True,
        },
    )
    if result is None or result.error or result.run_error or not result.run_id:
        reason = (
            result.error.detail if result and result.error else result.run_error if result else ""
        ) or "The task could not start."
        if held := totals(bet.team_id, work=work).reserved_cents:
            append(settings, bet, LedgerKind.RELEASE, held, f"refused:{work.id}:{reservations + 1}", work=work)
        move(work, WorkStage.WORKING, reason)
        return reason
    work.task_run_id = result.run_id
    work.save(using=WRITER_DB, update_fields=["task_run_id", "updated_at"])
    return {
        WorkKind.IDEA.value: "Building the pull request and the experiment.",
        WorkKind.CLEANUP.value: "Removing the flag from the code.",
    }.get(work.kind, "Checking the tracking code.")


def guard_runs(bet: Bet) -> None:
    now = timezone.now()
    held_by = (
        LedgerEntry.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, kind=LedgerKind.RESERVE)
        .values_list("work_item_id", flat=True)
    )
    for work in (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(Q(task_run_id__isnull=False) | Q(id__in=held_by), bet=bet)
    ):
        if work.task_run_id:
            run = tasks.get_task_run(work.task_run_id, team_id=bet.team_id)
        else:
            run = tasks.get_latest_run_by_task([str(work.task_id)]).get(str(work.task_id)) if work.task_id else None
        if run is not None and run.status in ACTIVE_RUN:
            if stop_run(bet, work, run, now):
                cancel_task_run(
                    run.id,
                    run.task_id,
                    bet.team_id,
                    reason="Bets stopped this run.",
                    source="bets",
                    requested_by_user_id=bet.owner_id,
                )
        elif (run is None or run.is_terminal) and not spend_pending(bet, work):
            if held := totals(bet.team_id, work=work).reserved_cents:
                reservations = held_by.filter(work_item=work).count()
                key = f"settled:{work.id}:{run.id if run else 'none'}:{reservations}"
                append(get_settings(bet.team_id), bet, LedgerKind.RELEASE, held, key, work=work)


def stop_run(bet: Bet, work: WorkItem, run: TaskRunDTO, now: datetime) -> bool:
    if totals(bet.team_id, work=work).spent_cents >= RUN_BUDGET_CENTS * MAX_ATTEMPTS:
        return True
    if work.kind == WorkKind.CLEANUP:
        return False
    building = work.stage == WorkStage.WORKING and not work.pr_url
    return (
        bet.status not in (BetStatus.SETTING_UP, BetStatus.RUNNING)
        or work.goal_version != bet.goal_version
        or work.stage in (WorkStage.DROPPED, WorkStage.STUCK)
        or building
        and now - (run.created_at or now) > timedelta(minutes=BUILD_MINUTES)
    )


def step(team: Team, user: User, bet: Bet) -> str:
    reconcile_spend(bet)
    guard_runs(bet)
    if bet.status not in (BetStatus.SETTING_UP, BetStatus.RUNNING):
        set_scout(bet, False)
        if bet.status in ENDED:
            return_unused(bet)
        return ""
    open_items = list(items(bet).filter(stage__in=OPEN).order_by("created_at"))
    tasks.refresh_pull_requests_for_tasks(bet.team_id, user.id, [work.task_id for work in open_items if work.task_id])
    for work in open_items:
        observe(team, user, bet, work)
    for idea in items(bet).filter(
        kind=WorkKind.IDEA,
        stage=WorkStage.DONE,
        experiment_id__isnull=False,
        finished_at__gte=timezone.now() - timedelta(days=2),
    ):
        if not items(bet).filter(key=f"cleanup:{idea.id}").exists():
            follow_cleanup(team, user, bet, idea)
    note = ""
    if bet.status == BetStatus.SETTING_UP:
        tracking = create_work(
            bet,
            user,
            kind=WorkKind.TRACKING,
            key=f"tracking:v{bet.goal_version}",
            title="Check how the goal is measured",
            note="Checking the tracking code.",
        )
        if tracking.stage == WorkStage.DONE and bet.target is None:
            note = "Bets found the insight. Check it and set the target in Edit bet."
        elif tracking.stage == WorkStage.DONE:
            facts = baseline(team, user, bet, since=tracking.merged_at)
            note = facts.note
            if facts.ready:
                bet.status = BetStatus.RUNNING
                bet.baseline_value = facts.value
                bet.baseline_at = timezone.now()
                bet.save(using=WRITER_DB, update_fields=["status", "baseline_value", "baseline_at", "updated_at"])
    if bet.status == BetStatus.RUNNING:
        ingest(bet)
        idea_open = items(bet).filter(kind=WorkKind.IDEA, stage__in=OPEN).exists()
        money = totals(bet.team_id, bet)
        confirmed, goal_note = goal_check(team, user, bet, idea_open)
        if confirmed:
            return stop(bet, BetStatus.REACHED, team, user)
        if not idea_open and money.available_cents <= 0 and money.reserved_cents <= 0:
            return stop(bet, BetStatus.SPENT, team, user)
        job, reason = scout_job(bet)
        failure = scout_failure(bet) if job else None
        if failure and failure.paused:
            set_scout(bet, False)
            note = failure.note
        elif job:
            started = run_scout(team, user, bet, reason)
            note = failure.note if failure and failure.note else started
        else:
            set_scout(bet, False)
            note = goal_note or reason
    dispatched = dispatch(bet, user)
    current = items(bet).filter(stage__in=OPEN).order_by("created_at").first()
    return dispatched or (current.note if current else "") or note


ENDED = (BetStatus.REACHED, BetStatus.SPENT, BetStatus.CLOSED)
END_NOTES = {
    BetStatus.REACHED: "The bet reached its goal.",
    BetStatus.SPENT: "The bet used its budget.",
    BetStatus.CLOSED: "The bet was closed.",
}


def return_unused(bet: Bet) -> None:
    available = totals(bet.team_id, bet).available_cents
    if available > 0:
        entries = LedgerEntry.objects.for_team(bet.team_id, canonical=True).using(WRITER_DB).filter(bet=bet).count()
        append(get_settings(bet.team_id), bet, LedgerKind.DEALLOCATE, available, f"return:{bet.id}:{entries}")


def finish(bet: Bet) -> None:
    note = END_NOTES.get(BetStatus(bet.status), "")
    for work in items(bet).filter(stage__in=OPEN):
        if work.kind == WorkKind.CLEANUP:
            move(work, WorkStage.DROPPED, f"{note} The flag cleanup continues in Tasks.")
            continue
        stop_idle_run(work, bet)
        if work.kind == WorkKind.IDEA:
            move(work, WorkStage.DROPPED, note, result={**work.result, "outcome": IdeaOutcome.DROPPED})
            end_experiment(bet, work)
        else:
            move(
                work,
                WorkStage.DROPPED,
                f"{note} Close the pull request if you do not need it." if work.pr_url else note,
            )
    return_unused(bet)


def stop(bet: Bet, status: BetStatus, team: Team | None = None, user: User | None = None) -> str:
    bet.status = status
    bet.save(using=WRITER_DB, update_fields=["status", "updated_at"])
    if team and user:
        money = totals(bet.team_id, bet)
        track_from_task(
            team, user, "bet ended", {"bet_id": str(bet.id), "status": status, "spent_cents": money.spent_cents}
        )
    set_scout(bet, False)
    finish(bet)
    return ""


def reconcile(team_id: int, bet_id: UUID) -> None:
    token = uuid4()
    now = timezone.now()
    claimed = (
        Bet.objects.for_team(team_id)
        .using(WRITER_DB)
        .filter(id=bet_id)
        .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
        .update(lease=token, lease_until=now + LEASE)
    )
    if not claimed:
        return
    try:
        bet = Bet.objects.for_team(team_id).using(WRITER_DB).get(id=bet_id)
        team = Team.objects.get(id=team_id)
        user = User.objects.filter(id=bet.owner_id, is_active=True).first()
        try:
            if user is None or not access.bets_enabled(team):
                raise PermissionDenied("The bet owner no longer has access.")
            access.require(team, user, write=True)
        except PermissionDenied as error:
            set_scout(bet, False)
            note = str(error.detail)
        else:
            note = step(team, user, bet)
            notify_owner(bet)
        Bet.objects.for_team(team_id).using(WRITER_DB).filter(id=bet_id, lease=token).update(note=note[:2000])
    except Exception as error:
        logger.exception("bets.reconcile_failed", team_id=team_id, bet_id=str(bet_id))
        Bet.objects.for_team(team_id).using(WRITER_DB).filter(id=bet_id, lease=token).update(
            note=f"Bets will retry: {str(error)[:300]}"
        )
        raise
    finally:
        Bet.objects.for_team(team_id).using(WRITER_DB).filter(id=bet_id, lease=token).update(
            lease=None, lease_until=None, reconcile_after=timezone.now() + timedelta(minutes=1)
        )


@transaction.atomic(using=WRITER_DB)
def act(
    bet: Bet, work_id: UUID, action: str, user: User | None = None, reason: str = "", plan: dict | None = None
) -> None:
    Bet.objects.for_team(bet.team_id).using(WRITER_DB).select_for_update().filter(id=bet.id).first()
    work = items(bet).select_for_update().filter(id=work_id).first()
    if work is None:
        raise ValidationError("This work does not belong to the bet's current goal.")
    if action == "build" and work.stage == WorkStage.PROPOSED:
        if items(bet).filter(kind=WorkKind.IDEA, stage__in=OPEN).exists():
            raise ValidationError("Another idea is in progress. Wait for its result.")
        if bet.status != BetStatus.RUNNING:
            raise ValidationError("The bet is not running.")
        if totals(bet.team_id, bet).available_cents <= 0:
            raise ValidationError("The budget is used. Add budget to build an idea.")
        owner = User.objects.get(id=bet.owner_id)
        number = (
            WorkItem.objects.for_team(bet.team_id)
            .using(WRITER_DB)
            .filter(bet=bet, kind=WorkKind.IDEA)
            .exclude(flag_key="")
            .count()
            + 1
        )
        move(
            work,
            WorkStage.WORKING,
            "Building the pull request and the experiment.",
            flag_key=f"bet-{bet.reference}-{number}",
            chosen_at=timezone.now(),
            chosen_by_id=user.id if user else None,
            plan={**work.plan, **plan, "approved": True} if plan else work.plan,
        )
        ensure_task(bet, owner, work)
    elif action == "dismiss" and work.stage == WorkStage.PROPOSED:
        if not reason.strip():
            raise ValidationError("Add a reason, so the Scout can learn from it.")
        move(work, WorkStage.DISMISSED, "Dismissed by the owner.", dismissed_reason=reason.strip()[:1000])
    elif action == "retry" and work.stage == WorkStage.STUCK:
        if work.kind == WorkKind.IDEA and items(bet).filter(kind=WorkKind.IDEA, stage__in=OPEN).exists():
            raise ValidationError("Another idea is in progress. Wait for its result.")
        move(work, WorkStage.WORKING, work.note, attempts=0, task_run_id=None)
    elif action == "extend" and work.stage == WorkStage.LIVE and work.plan.get("proposed_days"):
        planned = {key: value for key, value in work.plan.items() if key != "proposed_days"}
        move(work, WorkStage.LIVE, "Extended by the owner.", plan={**planned, "days": work.plan["proposed_days"]})
    elif action == "drop" and work.kind == WorkKind.IDEA and work.stage in OPEN:
        move(work, WorkStage.DROPPED, "Dropped by a person.", result={**work.result, "outcome": IdeaOutcome.DROPPED})
        end_experiment(bet, work)
    else:
        raise ValidationError("This action does not apply to this work.")
