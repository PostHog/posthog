from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

from posthog.dataclasses import frozen

from products.signals.backend.facade import api as signals
from products.tasks.backend.facade import api as tasks
from products.tasks.backend.facade.contracts import TaskRunDTO

from ..db import WRITER_DB
from ..facade.enums import BetStatus, IdeaSource, WorkKind, WorkStage
from ..models import Bet, WorkItem
from .ledger import totals
from .prompts import bet_context, history


def scout_body(bet: Bet) -> str:
    return f"""# Find ideas for a bet

The bet's goal, results so far, the owner's ideas and the rules for this run are attached to every run. Follow the attached rules.

Repository: {bet.repository}
"""


CHECK_RULES = """## Rules for this run
An idea is in an experiment now, on the feature flag `{flag}`. This run only checks the owner's ideas. Do not file ideas of your own.

1. For each owner idea below, file one report. The title starts with "Owner idea N:" (N is the number below) and then the idea. The summary starts with the word "Supported." or "Not supported." Then give the evidence. Add one line "Audience: <number> people a day" with how many people a day reach the place this idea touches, measured in PostHog, and link the insight you used.
2. The live experiment changes the data. Split every number by the variant of `{flag}`, or use data from before the experiment started. Say which one you used.
3. Evidence must be links to PostHog data in markdown link form: session replays you watched (with the time), insights or queries with the numbers, error groups, experiments. Never invent evidence.

Never write code, open pull requests, change flags or start experiments."""


RUN_RULES = """## Rules for this run
The owner chooses which idea to build. Nothing is built before that. Give the owner real choices with real evidence.

1. Start from the saved primary insight. Find where people drop off or slow down. Use funnels, paths, events, errors and session replays.
2. Read the code for that part of the product.
3. If the owner has ideas without a check, check each one first. File one report per owner idea. The title starts with "Owner idea N:" (N is the number below) and then the idea. The summary starts with the word "Supported." or "Not supported." Then give the evidence.
4. Then file up to 3 reports with your own ideas, the strongest first. Each report is one change that can move the primary metric and that we did not try or dismiss yet.
5. Each report has: the problem, the evidence, the proposed change, the files to touch, the expected effect, and the guardrail it could hurt. Add one line "Metric: <name>" with the metric this change moves first. When that is not the bet's primary metric, say how it leads to the primary metric. Add one line "Audience: <number> people a day" with how many people a day reach the place this change touches, measured in PostHog, and link the insight you used.
6. Evidence must be links to PostHog data in markdown link form: session replays you watched (with the time), insights or queries with the numbers, error groups, experiments. Never invent evidence. An idea without evidence is not an idea.

File nothing when you find no idea with evidence. Never write code, open pull requests, change flags or start experiments."""


def source_bet(team_id: int, source_id: str) -> Bet | None:
    try:
        bet_id, version = source_id.split(":v")
        return Bet.objects.for_team(team_id).using(WRITER_DB).filter(id=UUID(bet_id), goal_version=int(version)).first()
    except (ValueError, TypeError):
        return None


FIND = "find"
CHECK = "check"
TESTING = (WorkStage.WORKING, WorkStage.REVIEW, WorkStage.LIVE)


def scout_job(bet: Bet) -> tuple[str, str]:
    if bet.status != BetStatus.RUNNING:
        return ("", "The bet is not running.")
    if totals(bet.team_id, bet).available_cents <= 0:
        return ("", "The bet has no budget left.")
    ideas = WorkItem.objects.for_team(bet.team_id).using(WRITER_DB).filter(bet=bet, goal_version=bet.goal_version)
    unchecked = ideas.filter(source=IdeaSource.OWNER, stage=WorkStage.PROPOSED, report_id=None).exists()
    if ideas.filter(kind=WorkKind.IDEA, stage__in=TESTING).exists():
        if unchecked:
            return (CHECK, "Checking your idea while the current idea is tested.")
        return ("", "The bet is already testing an idea.")
    if ideas.filter(stage=WorkStage.PROPOSED).exists() and not unchecked:
        return ("", "Choose an idea to build.")
    return (FIND, "Looking for ideas.")


def scout_refusal(team_id: int, source_id: str) -> str | None:
    bet = source_bet(team_id, source_id)
    if bet is None:
        return "The bet is not running."
    job, reason = scout_job(bet)
    return None if job else reason


def live_flag(bet: Bet) -> str:
    live = (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, goal_version=bet.goal_version, kind=WorkKind.IDEA, stage__in=TESTING)
        .first()
    )
    return live.flag_key if live else ""


def owner_ideas(bet: Bet) -> str:
    unchecked = (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(
            bet=bet, goal_version=bet.goal_version, source=IdeaSource.OWNER, stage=WorkStage.PROPOSED, report_id=None
        )
        .order_by("created_at")
    )
    lines = [f"- Owner idea {work.key.removeprefix('owner:')}: {work.title}" for work in unchecked]
    return "\n".join(lines) or "No owner ideas to check."


def waiting_ideas(bet: Bet) -> str:
    waiting = (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(bet=bet, goal_version=bet.goal_version, stage=WorkStage.PROPOSED)
        .exclude(report_id=None)
        .order_by("created_at")
    )
    return "\n".join(f"- {work.title}" for work in waiting) or "None."


def scout_context(team_id: int, source_id: str) -> str:
    bet = source_bet(team_id, source_id)
    if bet is None:
        return ""
    return (
        f"{bet_context(bet)}\n\nBaseline: {bet.baseline_value}\n\n## What we tried\n{history(bet)}"
        f"\n\n## Owner ideas to check\n{owner_ideas(bet)}\n\n## Ideas already waiting for the owner\n{waiting_ideas(bet)}"
        f"\n\n{CHECK_RULES.format(flag=live_flag(bet)) if scout_job(bet)[0] == CHECK else RUN_RULES}"
    )[:24000]


FAILURE_LIMIT = 3
FAILURE_PAUSE = timedelta(hours=6)


def recent_scout_runs(bet: Bet, limit: int = 5) -> list[TaskRunDTO]:
    run_ids = signals.scout_run_ids_for_source(bet.team_id, "bets", [f"{bet.id}:v{bet.goal_version}"])
    runs = [run for run_id in run_ids if (run := tasks.get_task_run(run_id, team_id=bet.team_id))]
    epoch = timezone.make_aware(datetime.min.replace(year=1970))
    return sorted(runs, key=lambda run: run.created_at or epoch, reverse=True)[:limit]


@frozen
class ScoutFailure:
    paused: bool
    note: str


def scout_failure(bet: Bet) -> ScoutFailure:
    failed = []
    for run in recent_scout_runs(bet):
        if run.status != "failed":
            break
        failed.append(run)
    if not failed:
        return ScoutFailure(paused=False, note="")
    error = (failed[0].error_message or "no reason given")[:200]
    last = failed[0].updated_at or failed[0].created_at
    if len(failed) < FAILURE_LIMIT or (last and timezone.now() - last >= FAILURE_PAUSE):
        return ScoutFailure(paused=False, note=f"The last Scout run failed ({error}). Bets tries again.")
    return ScoutFailure(
        paused=True,
        note=f"The Scout failed {len(failed)} times in a row ({error}). Bets tries again in 6 hours. Check the Scout model in Settings.",
    )
