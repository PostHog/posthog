import re
from collections import deque
from io import TextIOBase

from django import forms
from django.contrib import messages
from django.core.management import CommandError, call_command
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

import structlog

from posthog.admin.console.panels import Owner, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Output, Page, Row, Table, ToolOperation
from posthog.management.commands.resave_cohorts import IncompleteResaveError
from posthog.utils import pluralize

from products.cohorts.backend.facade.api import (
    MAX_STATIC_COHORT_RESYNCS,
    StaticCohortResyncCandidate,
    StaticCohortResyncSkipReason,
    get_static_cohort_resync_candidates,
    queue_static_cohort_resyncs,
)

logger = structlog.get_logger(__name__)

FEATURE_FLAGS = Owner(name="Feature flags", crest="feature-flags")
# The command prints a line per team. A result page past this many lines is too long to read anyway.
MAX_OUTPUT_LINES = 400


class ResaveCohortsForm(forms.Form):
    team_id = forms.IntegerField(required=False, help_text="Leave empty to re-save the cohorts of every team.")
    batch_size = forms.IntegerField(initial=500, min_value=1, max_value=5000, help_text="Cohorts per batch.")
    dry_run = forms.BooleanField(
        initial=True, required=False, help_text="Report what would change without saving anything."
    )


class OutputTail(TextIOBase):
    """Keeps the last lines a command prints and counts them all, so a run across every team stays small in memory."""

    def __init__(self, keep: int) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=keep)
        self.line_count = 0
        self._partial = ""

    def write(self, text: str) -> int:
        *complete, self._partial = (self._partial + text).split("\n")
        for line in complete:
            if line.strip():
                self.lines.append(line)
                self.line_count += 1
        return len(text)

    def finish(self) -> list[str]:
        if self._partial.strip():
            self.lines.append(self._partial)
            self.line_count += 1
            self._partial = ""
        return list(self.lines)


class ResaveCohorts:
    """Runs the `resave_cohorts` management command from the console and keeps the end of what it printed."""

    @staticmethod
    def run(form: forms.Form) -> tuple[OutputTail, CommandError | None]:
        command_kwargs: dict[str, object] = {
            "batch_size": form.cleaned_data["batch_size"],
            "dry_run": form.cleaned_data["dry_run"],
        }
        team_id = form.cleaned_data.get("team_id")
        if team_id is not None:
            # Presence, not truthiness: team 0 has to reach the command, which rejects it. Reading it as
            # "no team given" would widen the run to every team. `call_command` skips argparse coercion for
            # keyword options, so the list that `--team-id` builds is passed already built.
            command_kwargs["team_id"] = [team_id]
        output = OutputTail(keep=MAX_OUTPUT_LINES)
        try:
            call_command("resave_cohorts", stdout=output, no_color=True, **command_kwargs)
        except IncompleteResaveError as error:
            # The run finished and kept its saves, so this is a result with problems, not a failure to start.
            return output, error
        return output, None


def resave_cohorts(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    try:
        output, problem = ResaveCohorts.run(form)
    except CommandError as error:
        messages.error(request, f"The re-save did not start: {error}")
        return HttpResponse(status=400)
    lines = output.finish()
    summary = lines[-1] if lines else "The command printed nothing."
    if problem is not None:
        messages.warning(request, f"The re-save finished with problems: {problem}")
    if form.cleaned_data["dry_run"]:
        # Nothing was saved, so a reload that runs it again is harmless.
        notice = "Dry run, nothing was saved."
        if len(lines) < output.line_count:
            notice += f" Showing the last {len(lines)} of {output.line_count} lines."
        return Page(blocks=(Notice(text=notice), Output(text="\n".join(lines))))
    messages.success(request, summary)
    return None


class ResyncStaticCohortsForm(forms.Form):
    cohorts = forms.CharField(
        label="Cohort IDs",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "One cohort ID per line, or separated by commas. Pick cohorts in the Django admin list and choose "
            "Re-sync static cohort from source query to fill this in."
        ),
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    def clean_cohorts(self) -> list[int]:
        tokens = re.findall(r"[^,\s]+", self.cleaned_data["cohorts"])
        if not tokens:
            raise forms.ValidationError("Enter at least one cohort ID.")
        if len(tokens) > MAX_STATIC_COHORT_RESYNCS:
            raise forms.ValidationError(f"Enter {MAX_STATIC_COHORT_RESYNCS} cohort IDs or fewer.")
        cohort_ids: list[int] = []
        for token in tokens:
            try:
                cohort_ids.append(int(token))
            except ValueError:
                raise forms.ValidationError(f"{token} is not a cohort ID.")
        return list(dict.fromkeys(cohort_ids))


SKIP_REASONS: dict[StaticCohortResyncSkipReason, str] = {
    "not_found": "no cohort has this ID",
    "not_static": "not static",
    "no_source_query": "no source query",
}


def _cohort_label(candidate: StaticCohortResyncCandidate) -> str:
    if candidate.name:
        return f"cohort {candidate.cohort_id} ({candidate.name})"
    return f"cohort {candidate.cohort_id}"


def _count_text(count: int | None) -> str:
    return "Not counted yet" if count is None else str(count)


def _resync_row(candidate: StaticCohortResyncCandidate) -> Row:
    if candidate.team_id is None:
        team = Cell(text="")
    else:
        team = Cell(
            text=f"{candidate.team_name} ({candidate.team_id})",
            href=reverse("admin_console_team", kwargs={"pk": candidate.team_id}),
        )
    if candidate.skip_reason is None:
        status = Cell(text="Re-sync", tone=Tone.SUCCESS)
    else:
        status = Cell(text=f"Skip: {SKIP_REASONS[candidate.skip_reason]}", tone=Tone.WARNING)
    return Row(
        cells=(
            Cell(text=str(candidate.cohort_id), mono=True),
            Cell(text=candidate.name or ""),
            team,
            Cell(text="" if candidate.skip_reason == "not_found" else _count_text(candidate.count)),
            status,
        )
    )


def preview_resync_static_cohorts(request: HttpRequest, form: forms.Form) -> Page:
    candidates = get_static_cohort_resync_candidates(cohort_ids=form.cleaned_data["cohorts"])
    resync_count = sum(1 for candidate in candidates if candidate.skip_reason is None)
    if resync_count == 0:
        form.add_error(
            "cohorts", "None of these cohorts can be re-synced. A cohort needs to be static and have a source query."
        )
        return Page(blocks=())
    return Page(
        blocks=(
            Notice(
                text=(
                    f"Adds to {pluralize(resync_count, 'static cohort')} the people who match its source query now "
                    "and are not members yet. Existing members stay. The count shows the members before the re-sync."
                )
            ),
            Table(
                columns=("ID", "Name", "Team", "Count", "Status"),
                rows=tuple(_resync_row(candidate) for candidate in candidates),
            ),
        )
    )


def resync_static_cohorts(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    result = queue_static_cohort_resyncs(cohort_ids=form.cleaned_data["cohorts"])
    for candidate in result.skipped:
        assert candidate.skip_reason is not None
        messages.warning(request, f"Skipped {_cohort_label(candidate)}: {SKIP_REASONS[candidate.skip_reason]}.")
    if not result.queued:
        messages.error(request, "Nothing was re-synced. None of these cohorts is static with a source query any more.")
        return HttpResponse(status=400)
    counts_before = "; ".join(
        f"{_cohort_label(candidate)}: {_count_text(candidate.count)}" for candidate in result.queued
    )
    messages.success(
        request,
        f"Queued a re-sync for {pluralize(len(result.queued), 'cohort')}. Counts before the re-sync: {counts_before}.",
    )
    return None


@console.register_tool
class ResaveCohortsTool(ConsoleTool):
    key = "resave-cohorts"
    title = "Re-save cohorts"
    owner = FEATURE_FLAGS
    group = "Data"
    description = (
        "Re-saves cohorts so their compiled bytecode and cohort type match the current backend logic, and re-syncs "
        "static cohorts from their source query."
    )

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "The re-save runs while the page loads, team by team, so a run across every team takes a "
                        "while. Start with a dry run: it shows each team's changes without saving them."
                    )
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="run",
                label="Re-save cohorts",
                handler=resave_cohorts,
                description="Re-saves the cohorts of one team, or of every team.",
                form_class=ResaveCohortsForm,
            ),
            ToolOperation(
                key="resync-static",
                label="Re-sync static cohorts",
                handler=resync_static_cohorts,
                preview=preview_resync_static_cohorts,
                danger=True,
                description="Adds the people who match each static cohort's source query now. Existing members stay.",
                form_class=ResyncStaticCohortsForm,
                # The Django admin action sends staff here with the cohorts they picked.
                form_initial={"cohorts": "\n".join(request.GET.getlist("cohort"))},
                undo_hint="PostHog Admin cannot remove the added people. Remove them from the cohort in the app.",
            ),
        ]


console.register_moved_page(
    old_path="admin/resave-cohorts/",
    title="Re-save cohorts",
    url="/admin/console/tools/resave-cohorts/",
)
