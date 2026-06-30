import json
from dataclasses import asdict
from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from products.notebooks.backend.facade import api as notebooks_api


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
        dry_run = bool(payload.get("dry_run", True))
        result = notebooks_api.migrate_notebooks_to_markdown(user=request.user, team_id=team_id, dry_run=dry_run)
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


def _result_to_response(result: Any) -> dict[str, Any]:
    data = asdict(result)
    data["message"] = (
        f"Dry run found {result.converted} notebook(s) to convert."
        if result.dry_run
        else f"Converted {result.converted} notebook(s) to markdown."
    )
    return data
