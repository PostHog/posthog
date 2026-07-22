import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.contrib import admin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from products.notebooks.backend.facade import api as notebooks_api

if TYPE_CHECKING:
    from posthog.models import User

DEFAULT_NOTEBOOK_MIGRATION_BATCH_SIZE = 100


class NotebookMarkdownMigrationForm(forms.Form):
    team_id = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="Only count and convert notebooks for this team id. Leave blank to target all teams.",
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Preview the notebooks that would be converted without saving anything.",
    )
    batch_size = forms.IntegerField(
        required=False,
        initial=DEFAULT_NOTEBOOK_MIGRATION_BATCH_SIZE,
        min_value=1,
        max_value=notebooks_api.MAX_NOTEBOOK_MIGRATION_BATCH_SIZE,
        help_text=(
            "Only process this many pending notebooks in one request. "
            f"Use repeated batches for large scopes. Maximum {notebooks_api.MAX_NOTEBOOK_MIGRATION_BATCH_SIZE}."
        ),
    )


def notebook_markdown_migration_view(request: HttpRequest) -> HttpResponse:
    context = {
        **admin.site.each_context(request),
        "form": NotebookMarkdownMigrationForm(),
        "title": "Markdown notebook migration",
    }
    return render(request, "admin/notebook_markdown_migration.html", context)


@require_GET
def notebook_markdown_migration_stats_view(request: HttpRequest) -> JsonResponse:
    try:
        team_id = _parse_team_id(request.GET.get("team_id"))
        stats = notebooks_api.get_markdown_notebook_migration_stats(team_id)
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    return JsonResponse(asdict(stats))


@require_POST
def notebook_markdown_migration_run_view(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "JSON body must be an object"}, status=400)

    try:
        team_id = _parse_team_id(payload.get("team_id"))
        dry_run = _parse_bool(payload.get("dry_run", True))
        batch_size = _parse_batch_size(payload.get("batch_size"))
        result = notebooks_api.migrate_notebooks_to_markdown(
            user=cast("User", request.user),
            team_id=team_id,
            dry_run=dry_run,
            batch_size=batch_size,
        )
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    return JsonResponse(_result_to_response(result))


def _parse_team_id(raw_team_id: Any) -> int | None:
    if raw_team_id is None or raw_team_id == "":
        return None
    try:
        return int(raw_team_id)
    except (TypeError, ValueError):
        raise ValueError("Team id must be an integer")


def _parse_batch_size(raw_batch_size: Any) -> int | None:
    if raw_batch_size is None or raw_batch_size == "":
        return DEFAULT_NOTEBOOK_MIGRATION_BATCH_SIZE
    try:
        batch_size = int(raw_batch_size)
    except (TypeError, ValueError):
        raise ValueError("Batch size must be an integer")
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1")
    if batch_size > notebooks_api.MAX_NOTEBOOK_MIGRATION_BATCH_SIZE:
        raise ValueError(f"Batch size must be {notebooks_api.MAX_NOTEBOOK_MIGRATION_BATCH_SIZE} or less")
    return batch_size


def _parse_bool(raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized_value = raw_value.strip().lower()
        if normalized_value in ("true", "1", "yes", "on"):
            return True
        if normalized_value in ("false", "0", "no", "off"):
            return False
    raise ValueError("Dry run must be a boolean")


def _result_to_response(result: Any) -> dict[str, Any]:
    data = asdict(result)
    data["message"] = (
        f"Dry run previewed {result.converted} notebook(s) from this batch."
        if result.dry_run
        else f"Converted {result.converted} notebook(s) to markdown. {result.pending_after} pending."
    )
    return data
