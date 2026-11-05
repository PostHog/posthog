from io import StringIO

from django import forms
from django.contrib import messages
from django.core.management import CommandError, call_command
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.admin.console.panels import Owner
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Notice, Output, Page, ToolOperation
from posthog.management.commands.resave_cohorts import IncompleteResaveError

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


class ResaveCohorts:
    """Runs the `resave_cohorts` management command from the console and keeps what it printed."""

    @staticmethod
    def run(form: forms.Form) -> tuple[str, CommandError | None]:
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
        output = StringIO()
        try:
            call_command("resave_cohorts", stdout=output, no_color=True, **command_kwargs)
        except IncompleteResaveError as error:
            # The run finished and kept its saves, so this is a result with problems, not a failure to start.
            return output.getvalue(), error
        return output.getvalue(), None


def resave_cohorts(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    try:
        output, problem = ResaveCohorts.run(form)
    except CommandError as error:
        messages.error(request, f"The re-save did not start: {error}")
        return HttpResponse(status=400)
    lines = output.strip().splitlines()
    summary = lines[-1] if lines else "The command printed nothing."
    if problem is not None:
        messages.warning(request, f"The re-save finished with problems: {problem}")
    if form.cleaned_data["dry_run"]:
        # Nothing was saved, so a reload that runs it again is harmless.
        shown = lines[-MAX_OUTPUT_LINES:]
        notice = "Dry run, nothing was saved."
        if len(shown) < len(lines):
            notice += f" Showing the last {MAX_OUTPUT_LINES} of {len(lines)} lines."
        return Page(blocks=(Notice(text=notice), Output(text="\n".join(shown))))
    messages.success(request, summary)
    return None


@console.register_tool
class ResaveCohortsTool(ConsoleTool):
    key = "resave-cohorts"
    title = "Re-save cohorts"
    owner = FEATURE_FLAGS
    group = "Data"
    description = "Re-saves cohorts so their compiled bytecode and cohort type match the current backend logic."

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
            )
        ]
