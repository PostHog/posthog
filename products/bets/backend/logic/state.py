import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TypedDict
from uuid import UUID

from django.utils import timezone

from posthog.dataclasses import frozen

from products.signals.backend.facade import api as signals

from ..facade.contracts import Money
from ..facade.enums import (
    BetActionKind as Kind,
    BetPhase as Phase,
    BetStatus,
    BetTile as Tile,
    BetWorkAction,
    IdeaOutcome,
    IdeaSource,
    WorkKind,
    WorkStage,
)
from ..models import Bet, WorkItem
from .ledger import totals, used_up
from .plan import EXPOSURE_GRACE, extend_question
from .scout import DISMISS_LIMIT, ScoutJob, scout_job
from .stages import LIVE, OPEN, items, source_id
from .workspace import get_settings

EMPTY_SCOUT_RUNS = 2
BASELINE_PATIENCE = timedelta(days=3)
ERROR_LIMIT = 3
NO_ACCESS = "The bet owner no longer has access."
FAILURES = re.compile(r"^Bets failed (\d+) times? in a row")
LATER = ("review", "scout-empty", "scout-dismissed")
ASKS = {
    "reached": ("The goal is reached", "Close the bet, or {raise}", "Goal reached"),
    "spent": ("The budget is used", "{continue}", "Budget used"),
    "access": ("The bet owner has no access", "{note}", "No access"),
    "errors": ("Bets keeps failing", "{note}", "Errors"),
    "target": ("Set the target", "Bets will measure this bet with {metric}. {fits} in Edit bet.", "Set the target"),
    "baseline": ("The baseline is not ready", "{note} {stalled}", "Check the measure"),
    "choose": ("Choose an idea to build", "{ready} Nothing is built until you choose one.", "Choose an idea"),
    "scout-empty": ("The Scout found no new ideas", "{empty}\n\n{summary}", "Add an idea"),
    "scout-dismissed": ("The Scout stopped", "{scout}", "Add an idea"),
    "scout-failing": ("The Scout keeps failing", "{scout}", "Scout failing"),
    "budget": ("The budget is used up", "Add budget to keep going, or close the bet.", "Budget"),
    "target-met": ("The goal already meets the target", "{met_at_start}", "Raise the target"),
    "extend": ("{title}", "{extend}", "Extend or stop"),
    "unseen": ("{title}", "{work_note}", "Check the deploy"),
    "review": ("{title}", "Review and merge the pull request when you are happy with it.", "Pull request"),
    "stuck": ("{title}", "{work_note}", "Needs attention"),
}
LINES = {
    "access": (Phase.WAITING, Tile.PROBLEM, "{problem}", "{note}"),
    "budget": (Phase.WAITING, Tile.PROBLEM, "The budget is used up", "{used} Add budget to keep going."),
    "target": (Phase.CHECKING_MEASURE, Tile.MEASURE, "Set the target to start", "{found}"),
    "tracking": (Phase.SETTING_UP, Tile.TRACKING, "Checking how the goal is measured", "{tracking}"),
    "stalled": (Phase.WAITING, Tile.PROBLEM, "The baseline is not ready", "{note}"),
    "baseline": (Phase.SETTING_UP, Tile.MEASURE, "Collecting a baseline", "{note}"),
    "stuck": (Phase.WAITING, Tile.PROBLEM, "{stopped}", "{work_note}"),
    "review": (Phase.REVIEWING, Tile.PULL_REQUEST, "Review the pull request", "{merge} starts when you merge it."),
    "building": (Phase.BUILDING, Tile.TRACKING, "Building an idea", "{building}"),
    "extend": (Phase.TESTING, Tile.EXPERIMENT, "Extend the test or stop it", "{extend}"),
    "unseen": (Phase.TESTING, Tile.EXPERIMENT, "Testing an idea", "{work_note}"),
    "testing": (Phase.TESTING, Tile.EXPERIMENT, "Testing an idea", "{testing}"),
    "target-met": (Phase.WAITING, Tile.PROBLEM, "The goal already meets the target", "{met_at_start}"),
    "confirming": (Phase.CONFIRMING_GOAL, Tile.MEASURE, "The goal is at the target", "{progress}{confirming}"),
    "choosing": (Phase.CHOOSING, Tile.IDEA, "Choose an idea to build", "{ready} Bets builds the one you choose."),
    "checking": (Phase.CHECKING_IDEAS, Tile.IDEA, "Checking your ideas", "{checking}"),
    "finding": (Phase.FINDING_IDEAS, Tile.SCOUT, "Finding ideas", "{finding}"),
    "scout-failing": (Phase.WAITING, Tile.PROBLEM, "The Scout keeps failing", "{scout}"),
    "scout-dismissed": (Phase.WAITING, Tile.IDLE, f"You dismissed the last {DISMISS_LIMIT} ideas", "{dismissed}"),
    "scout-empty": (Phase.WAITING, Tile.IDLE, "The Scout found no new ideas", "{empty}"),
    "scout": (Phase.WAITING, Tile.SCOUT, "{scout_label}", "{scout}"),
    "paused": (Phase.PAUSED, Tile.PAUSED, "The bet is paused", "Bets does no work until you resume the bet."),
    "reached": (Phase.ENDED, Tile.REACHED, "{reached}", "{ideas_summary}"),
    "spent": (Phase.ENDED, Tile.ENDED, "Budget used. The goal was not reached.", "{ideas_summary}"),
    "closed": (Phase.ENDED, Tile.ENDED, "{closed}", "{ideas_summary}"),
}
WORKING = ("tracking", "baseline", "building", "testing", "confirming", "checking", "finding")


class NextAction(TypedDict):
    id: str
    key: str
    bet_id: str
    bet_title: str
    title: str
    description: str
    label: str
    work_id: str | None
    url: str
    priority: int


@frozen
class BetAction:
    label: str
    kind: Kind
    primary: bool = True
    work_id: UUID | None = None
    work_action: BetWorkAction | None = None
    url: str = ""


BUTTONS = {
    "target": BetAction(label="Set the target", kind=Kind.EDIT),
    "target-met": BetAction(label="Raise the target", kind=Kind.EDIT),
    "budget": BetAction(label="Add budget", kind=Kind.BUDGET),
    "choosing": BetAction(label="See the ideas", kind=Kind.IDEAS),
    "review": BetAction(label="Review pull request", kind=Kind.PULL_REQUEST),
    "extend": BetAction(label="Extend to {days} days", kind=Kind.WORK, work_action=BetWorkAction.EXTEND),
    "stuck": BetAction(label="Try again", kind=Kind.WORK, primary=False, work_action=BetWorkAction.RETRY),
    "unseen": BetAction(label="Check the deploy", kind=Kind.WORK, primary=False),
    "stalled": BetAction(label="Edit bet", kind=Kind.EDIT, primary=False),
    "scout-failing": BetAction(label="Open settings", kind=Kind.SETTINGS, primary=False),
    "scout-dismissed": BetAction(label="Add an idea", kind=Kind.IDEAS, primary=False),
    "scout-empty": BetAction(label="Add an idea", kind=Kind.IDEAS, primary=False),
}
ALTERNATIVES = {"extend": BetAction(label="Stop test", kind=Kind.WORK, primary=False, work_action=BetWorkAction.DROP)}


@frozen
class ScoutState:
    label: str
    reason: str


@frozen
class BetState:
    phase: Phase
    tile: Tile
    headline: str
    detail: str
    subject: str
    work_id: UUID | None
    working: bool
    action: BetAction | None
    alternative: BetAction | None
    scout: ScoutState
    ready_ideas: int
    checking_ideas: int
    build_blocked: str
    can_add_idea: bool
    needs_you: bool
    actions: list[NextAction]


@frozen
class Facts:
    items: list[WorkItem]
    ready: int
    checking: int
    current: WorkItem | None
    tracking: WorkItem | None
    money: Money
    job: ScoutJob
    text: dict[str, str]
    asks: dict[str, NextAction]


def failure_note(previous: str, error: Exception) -> str:
    found = FAILURES.match(previous)
    count = int(found.group(1)) + 1 if found else 1
    return f"Bets failed {count} {'time' if count == 1 else 'times'} in a row and tries again: {str(error)[:300]}"


def goal_confirm_at(bet: Bet) -> datetime | None:
    if bet.goal_met_since is None:
        return None
    return bet.goal_met_since + timedelta(hours=get_settings(bet.team_id).goal_confirm_hours)


def takes_ideas(bet: Bet) -> bool:
    return bet.status not in (BetStatus.CLOSED, BetStatus.REACHED)


def build_refusal(bet: Bet, idea_open: bool) -> str:
    if idea_open:
        return "Wait for the current idea's result."
    if bet.status == BetStatus.PAUSED:
        return "Resume the bet to build an idea."
    if bet.status == BetStatus.SETTING_UP:
        return "The bet is still setting up."
    if bet.status == BetStatus.SPENT or totals(bet.team_id, bet).available_cents <= 0:
        return "The budget is used. Add budget to build an idea."
    if bet.status != BetStatus.RUNNING:
        return "Ideas can only be built while the bet runs."
    return ""


def number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def dollars(cents: int) -> str:
    return f"${cents // 100:,}" if cents % 100 == 0 else f"${cents / 100:,.2f}"


def day(moment: datetime | None) -> str:
    return f"{moment:%b} {moment.day}" if moment else ""


def plural(count: int, word: str) -> str:
    return f"{count} {word if count == 1 else word + 's'}"


def meets(bet: Bet, value: float | None) -> bool:
    if value is None or bet.target is None:
        return False
    target = float(bet.target)
    return value <= target if bet.direction == "decrease" else value >= target


def tested(outcome: str | None) -> bool:
    return bool(outcome) and outcome != IdeaOutcome.DROPPED


def ideas_summary(ideas: list[WorkItem]) -> str:
    outcomes = [work.result.get("outcome") for work in ideas]
    count = sum(1 for outcome in outcomes if tested(outcome))
    if not count:
        return "No ideas were tested"
    won = [work for work in ideas if work.result.get("outcome") == IdeaOutcome.WON]
    parts = [f"{outcomes.count(IdeaOutcome.WON)} of {plural(count, 'idea')} won"]
    if all("shipped" in work.result for work in won):
        shipped = sum(1 for work in won if work.result["shipped"])
        parts.append(f"{shipped} {'change' if shipped == 1 else 'changes'} shipped")
    return " · ".join(parts)


def unseen(work: WorkItem) -> bool:
    if work.merged_at is None or work.plan.get("exposed_at"):
        return False
    return timezone.now() - work.merged_at > EXPOSURE_GRACE


def work_key(work: WorkItem) -> str:
    if work.stage == WorkStage.LIVE:
        return "extend" if work.plan.get("proposed_days") else "unseen" if unseen(work) else "testing"
    return {WorkStage.REVIEW: "review", WorkStage.STUCK: "stuck", WorkStage.WORKING: "building"}.get(
        WorkStage(work.stage), ""
    )


def work_text(bet: Bet, work: WorkItem) -> dict[str, str]:
    step = (
        "measure check"
        if work.kind == WorkKind.TRACKING
        else "test"
        if work.merged_at
        else "review"
        if work.pr_url
        else ""
    )
    return {
        "title": work.title,
        "work_note": work.note,
        "extend": extend_question(work.plan) if work.plan.get("proposed_days") else "",
        "days": str(work.plan.get("proposed_days") or ""),
        "stopped": f"The {step} stopped" if step else "Building stopped",
        "merge": "Bets" if work.kind == WorkKind.TRACKING else "The test",
        "testing": "The goal is at the target. The bet ends when this test has a result."
        if bet.goal_met_since
        else work.note,
    }


def bet_text(
    bet: Bet, items: list[WorkItem], job: ScoutJob, money: Money, counts: tuple[int, int], value: float | None
) -> dict[str, str]:
    ready, checking = counts
    ideas = [work for work in items if work.kind == WorkKind.IDEA]
    outcomes = [work.result.get("outcome") for work in ideas]
    reached_on = day(bet.reached_at or bet.goal_met_since)
    target = number(float(bet.target)) if bet.target is not None else ""
    confirm_at = day(goal_confirm_at(bet))
    return {
        "note": bet.note,
        "continue": "Add budget to continue, or close the bet.",
        "raise": "raise the target and add budget to keep going.",
        "used": f"{dollars(money.spent_cents)} of {dollars(money.allocated_cents)} spent.",
        "found": f"Bets found a measure: {bet.goal_metric}. Check that it fits, then set the value to reach.",
        "ready": f"{plural(ready, 'idea')} {'is' if ready == 1 else 'are'} ready.",
        "metric": bet.goal_metric or "the goal",
        "fits": "Check that it fits, then set the value to reach",
        "stalled": "Check that the events reach PostHog, or change the measure in Edit bet.",
        "tracking": bet.note
        or f"Bets looks for the events behind {bet.goal_metric or 'the goal'}. This takes a few minutes.",
        "building": bet.note or "An agent writes the pull request.",
        "checking": job.problem or bet.note or f"Bets checks {plural(checking, 'idea')} against the code and the goal.",
        "finding": job.problem
        or bet.note
        or "Scout reads recordings, events and code to find changes that can move the goal.",
        "dismissed": "Bets stops looking until you add an idea.",
        "scout": job.reason,
        "scout_label": job.label,
        "progress": f"{number(value)} against a target of {target}. " if value is not None and target else "",
        "confirming": f"Bets confirms it on {confirm_at}.",
        "reached": f"Goal reached on {reached_on}" if reached_on else "Goal reached",
        "closed": " ".join(
            part
            for part in (
                f"Closed on {day(bet.closed_at)}" if bet.closed_at else "Closed",
                "" if any(tested(outcome) for outcome in outcomes) else "before any idea was tested",
            )
            if part
        ),
        "ideas_summary": ideas_summary(ideas),
        "met_at_start": f"{bet.goal_metric or 'The goal'} was {number(bet.baseline_value)} when the bet started, which already meets the target of {target}. Raise the target so the ideas have something to move."
        if bet.baseline_value is not None and target
        else "",
    }


def ask(bet: Bet, key: str, values: dict[str, str], work: WorkItem | None = None) -> NextAction:
    title, description, label = ASKS[key]
    return NextAction(
        id=f"{bet.id}:{work.id}:{key}" if work else f"{bet.id}:{key}",
        key=key,
        bet_id=str(bet.id),
        bet_title=bet.title,
        title=title.format(**values),
        description=description.format(**values).strip(),
        label=label,
        work_id=str(work.id) if work else None,
        url=work.pr_url if work and key in ("review", "unseen") else "",
        priority=int(key in LATER),
    )


def owner_asks(bet: Bet, found: Facts) -> list[NextAction]:
    if bet.status not in LIVE:
        return [ask(bet, key, found.text) for key in ("reached", "spent") if bet.status == key]
    setting_up, tracking, failures = bet.status == BetStatus.SETTING_UP, found.tracking, FAILURES.match(bet.note)
    empty: list[str] = []
    if bet.status == BetStatus.RUNNING and not found.ready and not found.checking and found.current is None:
        empty = signals.empty_scout_run_summaries(bet.team_id, "bets", source_id(bet))
    applies = {
        "access": bet.note == NO_ACCESS,
        "errors": bool(failures and int(failures.group(1)) >= ERROR_LIMIT),
        "target": setting_up and bool(bet.goal_insight) and bet.target is None,
        "baseline": setting_up
        and bet.target is not None
        and tracking is not None
        and tracking.stage == WorkStage.DONE
        and timezone.now() - (tracking.finished_at or tracking.updated_at) > BASELINE_PATIENCE,
        "choose": bool(found.ready) and found.current is None,
        "scout-empty": len(empty) >= EMPTY_SCOUT_RUNS,
        "scout-dismissed": found.job.ask == "scout-dismissed",
        "scout-failing": found.job.ask == "scout-failing",
        "budget": used_up(found.money),
        "target-met": bet.status == BetStatus.RUNNING and meets(bet, bet.baseline_value),
    }
    values = {
        **found.text,
        "empty": f"The last {len(empty)} Scout runs found no idea with enough evidence. Add your own idea for the Scout to check, or change the goal.",
        "summary": empty[0] if empty else "",
    }
    result = [ask(bet, key, values) for key, yes in applies.items() if yes] + [
        ask(bet, key, {**values, **work_text(bet, work)}, work)
        for work in found.items
        if (key := work_key(work)) in ASKS
    ]
    return sorted(result, key=lambda item: item["priority"])


def pick(bet: Bet, found: Facts) -> tuple[str, WorkItem | None]:
    asks, job, tracking = found.asks, found.job, found.tracking
    if bet.status not in LIVE:
        return (bet.status, None)
    if "access" in asks or "errors" in asks:
        return ("access", None)
    if "budget" in asks and (bet.status == BetStatus.SETTING_UP or found.current is None):
        return ("budget", None)
    if bet.status == BetStatus.SETTING_UP and "target" in asks:
        return ("target", None)
    if (
        bet.status == BetStatus.SETTING_UP
        and tracking is not None
        and tracking.stage in (WorkStage.REVIEW, WorkStage.STUCK)
    ):
        return (work_key(tracking), tracking)
    if bet.status == BetStatus.SETTING_UP:
        done = tracking is not None and tracking.stage == WorkStage.DONE
        return ("tracking" if not done else "stalled" if "baseline" in asks else "baseline", None)
    if found.current:
        return (work_key(found.current), found.current)
    if "target-met" in asks:
        return ("target-met", None)
    if bet.goal_met_since:
        return ("confirming", None)
    if found.ready:
        return ("choosing", None)
    if job.mode:
        return ("checking" if found.checking else "finding", None)
    return (job.ask or ("scout-empty" if "scout-empty" in asks else "scout"), None)


def bet_state(bet: Bet, value: float | None = None) -> BetState:
    work_items = list(items(bet).order_by("created_at"))
    proposed = [work for work in work_items if work.stage == WorkStage.PROPOSED]
    checking = sum(1 for work in proposed if work.source == IdeaSource.OWNER and work.report_id is None)
    money, job = totals(bet.team_id, bet), scout_job(bet)
    found = Facts(
        items=work_items,
        ready=len(proposed) - checking,
        checking=checking,
        current=next((work for work in work_items if work.kind == WorkKind.IDEA and work.stage in OPEN), None),
        tracking=next((work for work in work_items if work.kind == WorkKind.TRACKING), None),
        money=money,
        job=job,
        text=bet_text(bet, work_items, job, money, (len(proposed) - checking, checking), value),
        asks={},
    )
    actions = owner_asks(bet, found)
    found = replace(found, asks={item["key"]: item for item in actions})
    key, work = pick(bet, found)
    problem = next((item["title"] for item in actions if item["key"] in ("access", "errors")), "")
    empty = found.asks["scout-empty"]["description"].split("\n\n")[0] if "scout-empty" in found.asks else ""
    values = {**found.text, **(work_text(bet, work) if work else {}), "problem": problem, "empty": empty}
    phase, tile, headline, detail = LINES[key]
    button, alternative = BUTTONS.get(key), ALTERNATIVES.get(key)
    return BetState(
        phase=phase,
        tile=tile,
        headline=headline.format(**values),
        detail=detail.format(**values),
        subject=work.title if work and work.kind == WorkKind.IDEA else "",
        work_id=work.id if work else None,
        working=key in WORKING,
        action=button
        and replace(
            button,
            label=button.label.format(**values),
            work_id=work.id if work else None,
            url=work.pr_url if work else "",
        ),
        alternative=alternative and replace(alternative, work_id=work.id if work else None),
        scout=ScoutState(label=job.label, reason=empty or job.reason),
        ready_ideas=found.ready,
        checking_ideas=checking,
        build_blocked=build_refusal(bet, found.current is not None),
        can_add_idea=takes_ideas(bet),
        needs_you=bool(actions),
        actions=actions,
    )
