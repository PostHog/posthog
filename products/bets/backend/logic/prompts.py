from ..db import WRITER_DB
from ..facade.enums import WorkKind, WorkStage
from ..models import Bet, WorkItem


def bet_context(bet: Bet) -> str:
    guardrails = "\n".join(
        f"- {item['name']} (insight {item['insight']}): {'higher' if item.get('direction', 'increase') == 'increase' else 'lower'} is better, tolerate at most {float(item.get('max_regression', 0.05)):.0%} regression"
        for item in bet.secondary_metrics
    )
    return f"""## Bet
{bet.title}
{bet.statement}
Audience: {bet.audience or "everyone"}
Repositories: {", ".join(bet.repos)}
Primary metric: {bet.goal_metric}, saved insight {bet.goal_insight or "not created yet"}. Target: {f"{bet.target}{bet.unit}" if bet.target is not None else "not set yet"} ({"higher" if bet.direction == "increase" else "lower"} is better).
Guardrails:
{guardrails or "- none"}"""


def history(bet: Bet) -> str:
    ideas = (
        WorkItem.objects.for_team(bet.team_id)
        .using(WRITER_DB)
        .filter(
            bet=bet,
            goal_version=bet.goal_version,
            kind=WorkKind.IDEA,
            stage__in=[WorkStage.DONE, WorkStage.DROPPED, WorkStage.DISMISSED],
        )
        .order_by("updated_at")
    )
    lines = [
        f"- {idea.title}: dismissed by the owner. Reason: {idea.dismissed_reason}"
        if idea.stage == WorkStage.DISMISSED
        else f"- {idea.title}: {idea.result.get('outcome', idea.stage)}. {idea.result.get('verdict', '')} {idea.result.get('summary', '')}".strip()
        for idea in ideas
    ]
    return "\n".join(lines) or "No ideas tried yet."


RULES = """## Rules
- Never merge a pull request, push to the default branch, or deploy. People review and merge.
- Never edit the saved insights listed above. Propose a change in your summary instead.
- Never invent events, results or evidence.
- Do not wait for reviews or data."""


def instructions(bet: Bet, work: WorkItem) -> str:
    retry = (
        f"\n## Previous attempt\n{work.note}\nUpdate the existing pull request {work.pr_url} instead of opening a new one."
        if work.pr_url and work.note
        else f"\n## Previous attempt\n{work.note}"
        if work.note
        else ""
    )
    if work.kind == WorkKind.TRACKING and not bet.goal_insight:
        task = f"""## Task
Find or create the saved insight that measures the goal, then make sure it is measured.
The owner described the measure in words: {bet.goal_description}
1. Search the saved insights in PostHog for one that measures exactly this. A match is a trends insight that shows one line and measures the same kind of value: a count stays a count, and a share, rate or average stays a share, rate or average.
2. If no saved insight matches, create and save a trends insight that shows one line and measures it. For a share or rate, use two series and a formula, for example A / B. Name it after the metric.
3. List the events and properties that insight needs. Read the repositories and check that those events are captured where the behavior happens.
4. If tracking is missing or wrong, open one pull request that fixes it, with focused tests. If tracking is correct, open no pull request and say so.
End your last message with one line in this form, with the 8-character short ID of the saved insight:
Insight: <short id>"""
    elif work.kind == WorkKind.TRACKING:
        task = f"""## Task
Make sure the primary metric is measured.
1. Read the saved insight {bet.goal_insight} in PostHog and list the events and properties it needs.
2. Read the repository and check that those events are captured where the behavior happens.
3. If tracking is missing or wrong, open one pull request that fixes it, with focused tests. If tracking is correct, open no pull request and say so."""
    else:
        task = f"""## Task
Turn this idea into a pull request and an experiment.
Idea: {work.title}
{work.summary}

1. Implement the change in the repository behind the feature flag `{work.flag_key}`. Users without the flag see today's behavior. Keep the diff small and add focused tests.
2. Open one pull request. Mention the flag key and the experiment in its description.
3. In PostHog, create an experiment that uses the feature flag `{work.flag_key}` with a control and a test variant. Use the bet's primary metric as the experiment's primary metric, and each guardrail as a secondary metric.
4. Launch the experiment. Nobody is exposed until the pull request is merged and deployed, so launching now is safe.
End with a short summary of the change and the experiment."""
    return f"""{bet_context(bet)}

## What we tried
{history(bet)}

{task}
{retry}

{RULES}
"""
