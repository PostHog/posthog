"""Local eval for the Slack repo-selection flow — the canonical "how to test locally" tool.

Replicates the production cascade → Haiku gate → discovery agent path against a real
team with a real GitHub integration, without needing a `slack-posthog-code` Integration
row or any actual Slack traffic. Each case declares its expected terminal stage/outcome;
the eval prints a pass/fail summary so you can re-run after touching repo selection
and spot regressions immediately.

Lives next to the Slack workflow it exercises (`posthog_code_slack_mention.py`) rather
than in `posthog/management/commands/` because (a) it's co-located with the thing it
tests and (b) `products/slack_app/` can't tach-depend on `products/tasks/`, which the
eval needs to import from.

# Prerequisites

- `DEBUG=1` (refuses to run otherwise — burns sandbox + LLM credits)
- A team with a connected GitHub integration that has >=2 cached repos
- Dev stack up (sandbox manager + temporal + LLM creds): `./bin/start` / `hogli start`

# Usage

    # Full eval (~3-6 min — most cost is the agent runs)
    python posthog/temporal/ai/eval_slack_repo_selection.py --team-id 1 --user-id 1

    # Iterate fast on cascade-only changes (no LLM at all)
    python posthog/temporal/ai/eval_slack_repo_selection.py --team-id 1 --user-id 1 --skip-llm

    # Iterate on Haiku changes without paying for agent runs
    python posthog/temporal/ai/eval_slack_repo_selection.py --team-id 1 --user-id 1 --skip-agent

    # Single case
    python posthog/temporal/ai/eval_slack_repo_selection.py --team-id 1 --user-id 1 --case vague_code_bug

    # See what the Slack picker message renders on each failure mode
    python posthog/temporal/ai/eval_slack_repo_selection.py --team-id 1 --user-id 1 --case vague_code_bug \\
        --show-picker-guidance

    # See the case catalogue without running anything
    python posthog/temporal/ai/eval_slack_repo_selection.py --list-cases

# Reading the output

Each case prints what each stage decides, then the summary tallies PASS / FAIL / SKIP.
For `agent → found` cases, the agent's `reason` text is the quality signal — it should
cite cache evidence (tree_paths matches, README excerpts), not vibes.

To force the failure modes the picker fallback handles:
- `RepoSelectionUnavailableError`: temporarily set `archived=True` on all rows in
  `IntegrationRepositoryCacheEntry` for the team, run any agent case.
- `RepoSelectionRejectedError`: hard to force reliably; use `--show-picker-guidance`
  to preview what the user would see if it did fire.
"""

# ruff: noqa: T201, E402

from __future__ import annotations

import os
import sys
import asyncio
import argparse
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Must run as `python posthog/temporal/ai/eval_slack_repo_selection.py` (not `python -m ...`):
# `python -m` would import `posthog/temporal/ai/__init__.py` first, which loads workflows that
# reference Django models before django.setup() has a chance to fire.
_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

import django

django.setup()

from django.conf import settings

from posthog.models import Team
from posthog.temporal.ai.posthog_code_slack_mention import POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE

from products.slack_app.backend.api import _extract_explicit_repo, classify_task_needs_repo
from products.tasks.backend.models import Task
from products.tasks.backend.repo_selection import (
    RepoSelectionRejectedError,
    RepoSelectionResult,
    RepoSelectionUnavailableError,
    resolve_team_github_integration,
    select_repository,
)

Stage = Literal["cascade", "haiku", "agent", "skipped"]
Outcome = Literal[
    "auto",  # cascade picked a repo (explicit mention / single repo)
    "no_repo",  # cascade or Haiku decided no repo is needed
    "found",  # agent picked a repo
    "no_match",  # agent returned None (no plausible candidate)
    "rejected",  # agent returned a repo not in the candidate list
    "unavailable",  # agent raised RepoSelectionUnavailableError
    "crashed",  # agent raised unexpected exception
    "skipped",  # case wasn't run due to --skip-* flag
]


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    # `{first_repo}` is substituted with the team's first connected repo for the explicit case.
    text_template: str
    thread_messages: list[dict[str, str]]
    expected_stage: Stage
    expected_outcome: Outcome
    # Optional human note explaining current behavior quirks.
    note: str = ""


@dataclass
class CaseResult:
    case: Case
    actual_stage: Stage
    actual_outcome: Outcome
    detail: str = ""  # repo name, error type, etc.

    @property
    def status(self) -> Literal["PASS", "FAIL", "SKIP"]:
        if self.actual_stage == "skipped":
            return "SKIP"
        if (self.actual_stage, self.actual_outcome) == (self.case.expected_stage, self.case.expected_outcome):
            return "PASS"
        return "FAIL"


# Cases are parameterized so they work across teams; `{first_repo}` is substituted at runtime.
# Expected outcomes match observed behavior on master + this PR — the eval is a regression
# baseline. Cases with `note` fields call out known quirks.
CASES: list[Case] = [
    # --- Cascade short-circuit -------------------------------------------------
    Case(
        name="explicit_mention",
        description="Cascade picks the repo directly when the text contains a connected org/repo.",
        text_template="@PostHog can you look at {first_repo} and fix the readme typo",
        thread_messages=[{"user": "tester", "text": "@PostHog can you look at {first_repo} and fix the readme typo"}],
        expected_stage="cascade",
        expected_outcome="auto",
    ),
    # --- Haiku gate short-circuits (heuristic + LLM) ---------------------------
    Case(
        name="billing_question",
        description="Haiku LLM should classify as no-repo (billing/account question).",
        text_template="@PostHog how do I update the credit card on our subscription?",
        thread_messages=[{"user": "tester", "text": "@PostHog how do I update the credit card on our subscription?"}],
        expected_stage="haiku",
        expected_outcome="no_repo",
    ),
    Case(
        name="dashboard_config",
        description="Haiku heuristic short-circuits on 'dashboard' with no explicit code pattern.",
        text_template="@PostHog the dashboard tile filters are not persisting across refreshes",
        thread_messages=[
            {"user": "tester", "text": "@PostHog the dashboard tile filters are not persisting across refreshes"}
        ],
        expected_stage="haiku",
        expected_outcome="no_repo",
    ),
    Case(
        name="marketing_site",
        description="Haiku LLM filters as ops/perf rather than code change.",
        text_template="@PostHog the docs site loads really slowly on mobile",
        thread_messages=[
            {"user": "tester", "text": "@PostHog the docs site loads really slowly on mobile"},
            {"user": "other", "text": "yeah I noticed the same on /docs/getting-started"},
        ],
        expected_stage="haiku",
        expected_outcome="no_repo",
        note=(
            "Ideally the agent would route this to a docs/marketing repo if connected. "
            "Haiku LLM treats it as a perf/CDN question instead. Out of this PR's scope; "
            "candidate for a follow-up Haiku-tuning PR backed by this eval."
        ),
    ),
    Case(
        name="sdk_specific_trace_trip",
        description="Haiku heuristic trips on 'trace' in 'stack trace'.",
        text_template="@PostHog the iOS SDK is crashing on app launch after upgrade to 3.19",
        thread_messages=[
            {"user": "tester", "text": "@PostHog the iOS SDK is crashing on app launch after upgrade to 3.19"},
            {"user": "other", "text": "stack trace shows PostHogReplay.start() failing"},
        ],
        expected_stage="haiku",
        expected_outcome="no_repo",
        note=(
            "Pre-existing heuristic false negative: 'trace' is in product_debug_terms "
            "(for APM-trace queries) but matches 'stack trace' too. Same scope note as marketing_site."
        ),
    ),
    # --- Agent path (the new logic this PR introduces) -------------------------
    Case(
        name="vague_code_bug",
        description="Vague but code-flavored; agent should disambiguate from cache.",
        text_template="@PostHog there's a bug in how we render user signup, can you fix it",
        thread_messages=[
            {"user": "tester", "text": "@PostHog there's a bug in how we render user signup, can you fix it"}
        ],
        expected_stage="agent",
        expected_outcome="found",
    ),
    Case(
        name="api_viewset",
        description="Explicit code pattern ('viewset') bypasses heuristic; agent picks the API repo.",
        text_template="@PostHog the /api/projects/ viewset crashes on large payloads, can you fix it",
        thread_messages=[
            {"user": "tester", "text": "@PostHog the /api/projects/ viewset crashes on large payloads, can you fix it"}
        ],
        expected_stage="agent",
        expected_outcome="found",
    ),
    Case(
        name="explicit_code_file",
        description="Explicit '.tsx' file extension bypasses heuristic; agent picks the frontend repo.",
        text_template="@PostHog add a Cancel button to the signup form in the .tsx component",
        thread_messages=[
            {"user": "tester", "text": "@PostHog add a Cancel button to the signup form in the .tsx component"}
        ],
        expected_stage="agent",
        expected_outcome="found",
    ),
    Case(
        name="refactor_request",
        description="No debug terms, code-flavored verb; Haiku LLM should allow, agent picks.",
        text_template="@PostHog please refactor the user permission check into a single helper",
        thread_messages=[
            {"user": "tester", "text": "@PostHog please refactor the user permission check into a single helper"}
        ],
        expected_stage="agent",
        expected_outcome="found",
    ),
]


@dataclass
class RunFlags:
    skip_llm: bool = False
    skip_agent: bool = False
    show_picker: bool = False


@dataclass
class TeamContext:
    team: Team
    team_id: int
    user_id: int
    all_repos: list[str]
    first_repo: str
    results: list[CaseResult] = field(default_factory=list)


class CommandError(Exception):
    """Raised on user-visible misconfiguration — translated to exit 1 in main()."""


class _Style:
    """Minimal stand-in for Django BaseCommand.style — just enough for our colored output."""

    @staticmethod
    def _wrap(code: int, s: str) -> str:
        return f"\033[{code}m{s}\033[0m"

    def SUCCESS(self, s: str) -> str:
        return self._wrap(32, s)

    def ERROR(self, s: str) -> str:
        return self._wrap(31, s)

    def WARNING(self, s: str) -> str:
        return self._wrap(33, s)

    def MIGRATE_HEADING(self, s: str) -> str:
        return self._wrap(36, s)

    def HTTP_INFO(self, s: str) -> str:
        return self._wrap(35, s)


class _Stdout:
    def write(self, s: str = "") -> None:
        print(s)


class Command:
    """Eval runner — keeps the BaseCommand-shaped API so the body reads identically to a manage.py command."""

    def __init__(self) -> None:
        self.stdout = _Stdout()
        self.style = _Style()

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=False, help="Team ID with a GitHub integration.")
        parser.add_argument("--user-id", type=int, required=False, help="User ID to attribute sandbox runs to.")
        parser.add_argument("--case", type=str, default=None, help="Run a single case by name.")
        parser.add_argument("--list-cases", action="store_true", help="Print available cases and exit.")
        parser.add_argument(
            "--skip-llm",
            action="store_true",
            help="Stop after cascade. No LLM calls. Iterate fast on _extract_explicit_repo changes.",
        )
        parser.add_argument(
            "--skip-agent",
            action="store_true",
            help="Stop after Haiku. No sandbox runs. Iterate on classify_task_needs_repo changes.",
        )
        parser.add_argument(
            "--show-picker-guidance",
            action="store_true",
            help="After each agent run, preview the picker guidance string for each failure mode.",
        )

    def handle(self, *args, **options):
        if options["list_cases"]:
            for case in CASES:
                self.stdout.write(f"  {case.name:24s} → {case.expected_stage}/{case.expected_outcome}")
                self.stdout.write(f"  {'':24s}   {case.description}")
            return

        if not settings.DEBUG:
            raise CommandError("Refusing to run outside DEBUG mode — this consumes sandbox + LLM credits.")
        if options["team_id"] is None or options["user_id"] is None:
            raise CommandError("--team-id and --user-id are required (unless --list-cases).")

        flags = RunFlags(
            skip_llm=options["skip_llm"],
            skip_agent=options["skip_agent"],
            show_picker=options["show_picker_guidance"],
        )
        ctx = self._build_context(team_id=options["team_id"], user_id=options["user_id"])

        cases_to_run = [c for c in CASES if c.name == options["case"]] if options["case"] else CASES
        if options["case"] and not cases_to_run:
            raise CommandError(f"Unknown case '{options['case']}'. Use --list-cases to see options.")

        for case in cases_to_run:
            result = self._run_case(case, ctx=ctx, flags=flags)
            ctx.results.append(result)
            if flags.show_picker and result.actual_stage == "agent":
                self._print_picker_previews()

        self._print_summary(ctx.results)

    # --- Setup ----------------------------------------------------------------

    def _build_context(self, *, team_id: int, user_id: int) -> TeamContext:
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"Team {team_id} not found.")

        github = resolve_team_github_integration(team_id)
        if github is None:
            raise CommandError(
                f"Team {team_id} has no GitHub integration. Connect one (with >=2 repos) before running."
            )
        all_repos = sorted(
            {
                entry["full_name"]
                for entry in github.list_all_cached_repositories(max_repos=1000)
                if entry.get("full_name")
            }
        )
        if len(all_repos) < 2:
            raise CommandError(f"Team {team_id} has {len(all_repos)} connected repo(s). Agent path requires >=2.")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Team: {team.name} (id={team.id})"))
        self.stdout.write(f"Connected repos ({len(all_repos)}):")
        for repo in all_repos[:20]:
            self.stdout.write(f"  - {repo}")
        if len(all_repos) > 20:
            self.stdout.write(f"  ... and {len(all_repos) - 20} more")
        self.stdout.write("")

        return TeamContext(team=team, team_id=team_id, user_id=user_id, all_repos=all_repos, first_repo=all_repos[0])

    # --- Case execution -------------------------------------------------------

    def _run_case(self, case: Case, *, ctx: TeamContext, flags: RunFlags) -> CaseResult:
        text = case.text_template.format(first_repo=ctx.first_repo)
        thread_messages = [
            {**msg, "text": msg["text"].format(first_repo=ctx.first_repo)} for msg in case.thread_messages
        ]

        self.stdout.write(self.style.MIGRATE_HEADING(f"── {case.name} ──"))
        self.stdout.write(f"  text:     {text}")
        self.stdout.write(f"  expected: {case.expected_stage}/{case.expected_outcome}")

        # Stage 1: cascade (synchronous, no LLM)
        explicit = _extract_explicit_repo(text, ctx.all_repos)
        if explicit:
            self.stdout.write(self.style.SUCCESS(f"  cascade → auto: {explicit}"))
            return CaseResult(case=case, actual_stage="cascade", actual_outcome="auto", detail=explicit)
        self.stdout.write("  cascade → needs_agent (no explicit mention, >=2 repos)")

        if flags.skip_llm:
            self.stdout.write(self.style.WARNING("  skipped (--skip-llm)"))
            return CaseResult(case=case, actual_stage="skipped", actual_outcome="skipped")

        # Stage 2: Haiku gate (heuristic + LLM)
        needs_repo = classify_task_needs_repo(text, thread_messages)
        if not needs_repo:
            self.stdout.write(self.style.SUCCESS("  haiku → no_repo (task doesn't need code)"))
            return CaseResult(case=case, actual_stage="haiku", actual_outcome="no_repo")
        self.stdout.write("  haiku → needs_repo")

        if flags.skip_agent:
            self.stdout.write(self.style.WARNING("  skipped (--skip-agent)"))
            return CaseResult(case=case, actual_stage="skipped", actual_outcome="skipped")

        # Stage 3: discovery agent (full sandbox)
        self.stdout.write("  agent → running (30-60s)...")
        context = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)
        try:
            result: RepoSelectionResult = asyncio.run(
                select_repository(
                    team_id=ctx.team_id,
                    user_id=ctx.user_id,
                    context=context,
                    origin_product=Task.OriginProduct.SLACK,
                )
            )
            if result.repository is None:
                self.stdout.write(self.style.WARNING(f"  agent → no_match: {result.reason}"))
                return CaseResult(case=case, actual_stage="agent", actual_outcome="no_match", detail=result.reason)
            self.stdout.write(self.style.SUCCESS(f"  agent → found: {result.repository}"))
            self.stdout.write(f"    reason: {self._wrap(result.reason)}")
            return CaseResult(case=case, actual_stage="agent", actual_outcome="found", detail=result.repository)
        except RepoSelectionRejectedError as exc:
            self.stdout.write(self.style.ERROR(f"  agent → rejected (hallucinated '{exc.returned_repository}')"))
            return CaseResult(
                case=case, actual_stage="agent", actual_outcome="rejected", detail=exc.returned_repository
            )
        except RepoSelectionUnavailableError as exc:
            self.stdout.write(self.style.ERROR(f"  agent → unavailable: {exc.reason}"))
            return CaseResult(case=case, actual_stage="agent", actual_outcome="unavailable", detail=exc.reason)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  agent → crashed ({type(exc).__name__}): {exc}"))
            return CaseResult(case=case, actual_stage="agent", actual_outcome="crashed", detail=type(exc).__name__)

    # --- Output helpers -------------------------------------------------------

    def _print_picker_previews(self) -> None:
        self.stdout.write("  picker preview (what the user sees on each agent failure):")
        for label, reason in [
            ("rejected", "Agent returned an invalid repository: posthog/foo"),
            (
                "unavailable",
                "Repo selection unavailable: No connected GitHub repositories are eligible (archived or missing cache data).",
            ),
            ("crashed", "Agent failed: TimeoutError"),
        ]:
            picker_guidance = f"_{reason}_\n\n{POSTHOG_CODE_SLACK_MENTION_PICKER_GUIDANCE}"
            self.stdout.write(self.style.HTTP_INFO(f"    [{label}]"))
            for line in picker_guidance.splitlines():
                self.stdout.write(f"      {line}")

    def _print_summary(self, results: list[CaseResult]) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("── summary ──"))

        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        skipped = sum(1 for r in results if r.status == "SKIP")

        for r in results:
            badge = {"PASS": self.style.SUCCESS, "FAIL": self.style.ERROR, "SKIP": self.style.WARNING}[r.status]
            actual = f"{r.actual_stage}/{r.actual_outcome}"
            detail = f" ({r.detail})" if r.detail and r.status == "PASS" else ""
            self.stdout.write(f"  {badge(r.status):>14s}  {r.case.name:24s}  → {actual}{detail}")
            if r.status == "FAIL":
                self.stdout.write(f"        expected {r.case.expected_stage}/{r.case.expected_outcome}")
            if r.case.note and r.status != "SKIP":
                self.stdout.write(
                    textwrap.fill(r.case.note, width=100, initial_indent="        note: ", subsequent_indent=" " * 14)
                )

        self.stdout.write("")
        total = len(results)
        self.stdout.write(f"  {passed} passed, {failed} failed, {skipped} skipped ({total} total)")

    @staticmethod
    def _wrap(text: str, width: int = 90, indent: str = "      ") -> str:
        return textwrap.fill(text, width=width, subsequent_indent=indent)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python posthog/temporal/ai/eval_slack_repo_selection.py",
        description="Eval the Slack repo selection flow (cascade → Haiku gate → agent) on a real team.",
    )
    cmd = Command()
    cmd.add_arguments(parser)
    options = vars(parser.parse_args())
    try:
        cmd.handle(**options)
    except CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
