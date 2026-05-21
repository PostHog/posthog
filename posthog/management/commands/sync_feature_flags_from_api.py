import os
import argparse
from collections.abc import Callable
from typing import Any

from django.core.management.base import BaseCommand

import requests

from posthog.models import FeatureFlag, Project, User

POSTHOG_US_HOST = "https://us.posthog.com"
POSTHOG_US_PROJECT_ID = 2

DEFAULT_BOOLEAN_FILTERS: dict[str, Any] = {
    "groups": [{"properties": [], "rollout_percentage": 100}],
    "payloads": {},
}


def _fetch_flag_definitions(
    personal_api_key: str,
    project_id: int,
    host: str,
    output_fn: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Fetch all feature flag definitions for a project from the authenticated list endpoint."""
    flags: list[dict[str, Any]] = []
    next_url: str | None = f"{host}/api/projects/{project_id}/feature_flags/?limit=200"
    page = 0
    while next_url:
        page += 1
        output_fn(f"Fetching feature flag definitions (page {page})...")
        response = requests.get(
            next_url,
            headers={"Authorization": f"Bearer {personal_api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        flags.extend(data.get("results", []))
        next_url = data.get("next")
    output_fn(f"Fetched {len(flags)} feature flag definition(s) from {host}")
    return flags


def sync_feature_flags_from_api(
    personal_api_key: str | None = None,
    project_id: int = POSTHOG_US_PROJECT_ID,
    host: str = POSTHOG_US_HOST,
    output_fn: Callable[[str], None] = print,
) -> None:
    """
    Fetch feature flag definitions from the PostHog API and sync them to the local database.

    Uses the authenticated /api/projects/:id/feature_flags/ endpoint so that the full
    flag definition (including filters.multivariate.variants) is preserved — earlier
    revisions fetched evaluated flag values from /flags?v=2, which flattened
    multivariate flags into booleans.

    Args:
        personal_api_key: Personal API key with feature_flag:read scope for `project_id`.
            Falls back to the POSTHOG_PERSONAL_API_KEY env var.
        project_id: PostHog project to read definitions from (defaults to PostHog's US prod project).
        host: PostHog host to read from (defaults to us.posthog.com).
        output_fn: Function to call for output (defaults to print, can use self.stdout.write for management commands).
    """
    if personal_api_key is None:
        personal_api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY")

    if not personal_api_key:
        output_fn(
            "Skipping feature flag sync: no personal API key provided. "
            "Set the POSTHOG_PERSONAL_API_KEY env var (or pass --personal_api_key) "
            "with a key that has feature_flag:read scope on the source project."
        )
        return

    flag_definitions = _fetch_flag_definitions(personal_api_key, project_id, host, output_fn)

    if not flag_definitions:
        output_fn("No flags found in API response")
        return

    first_user = User.objects.first()
    if not first_user:
        output_fn("No users found in database")
        return

    for project in Project.objects.all():
        output_fn(f"\nProcessing project {project.id} - {project.name or ''}")
        output_fn("=" * 50)

        existing_flags = set(
            FeatureFlag.objects_including_soft_deleted.filter(team__project_id=project.id).values_list("key", flat=True)
        )
        deleted_flags = set(
            FeatureFlag.objects_including_soft_deleted.filter(team__project_id=project.id, deleted=True).values_list(
                "key", flat=True
            )
        )

        active_in_api = sum(1 for flag in flag_definitions if flag.get("active", False))
        undeleted_count = 0
        created_count = 0
        activated_count = 0
        deactivated_count = 0
        unchanged_count = 0

        for flag in flag_definitions:
            flag_key = flag.get("key")
            if not flag_key:
                continue
            is_active = flag.get("active", False)
            filters = flag.get("filters") or DEFAULT_BOOLEAN_FILTERS

            if flag_key in deleted_flags and is_active:
                ff = FeatureFlag.objects_including_soft_deleted.get(team__project_id=project.id, key=flag_key)
                ff.deleted = False
                ff.active = True
                ff.filters = filters
                ff.save()
                output_fn(f"Undeleted feature flag '{flag_key}'")
                undeleted_count += 1

            elif flag_key not in existing_flags and is_active:
                FeatureFlag.objects.create(
                    team=project.teams.first(),
                    name=flag.get("name") or flag_key,
                    key=flag_key,
                    created_by=first_user,
                    active=True,
                    filters=filters,
                )
                output_fn(f"Created feature flag '{flag_key}'")
                created_count += 1

            else:
                ff = FeatureFlag.objects.filter(team__project_id=project.id, key=flag_key).first()
                if ff and ff.active != is_active:
                    ff.active = is_active
                    ff.save()
                    if is_active:
                        output_fn(f"Activated feature flag '{flag_key}'")
                        activated_count += 1
                    else:
                        output_fn(f"Deactivated feature flag '{flag_key}'")
                        deactivated_count += 1
                else:
                    unchanged_count += 1

        output_fn("\nProject Summary")
        output_fn("-" * 20)
        output_fn(f"Active flags from API: {active_in_api}")
        output_fn(f"Existing: {len(existing_flags)}")
        output_fn(f"Undeleted: {undeleted_count}")
        output_fn(f"Created: {created_count}")
        output_fn(f"Activated: {activated_count}")
        output_fn(f"Deactivated: {deactivated_count}")
        output_fn(f"Unchanged: {unchanged_count}")
        output_fn(f"Total after sync: {len(existing_flags) + created_count}")

    output_fn("\nFeature flag sync complete.")


class Command(BaseCommand):
    help = "Sync feature flags by fetching their definitions from the PostHog API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--personal_api_key",
            type=str,
            help="Personal API key with feature_flag:read scope. Defaults to the POSTHOG_PERSONAL_API_KEY env var.",
        )
        parser.add_argument(
            "--project_id",
            type=int,
            default=POSTHOG_US_PROJECT_ID,
            help=f"PostHog project ID to read flag definitions from (default: {POSTHOG_US_PROJECT_ID}).",
        )
        parser.add_argument(
            "--host",
            type=str,
            default=POSTHOG_US_HOST,
            help=f"PostHog host to read flag definitions from (default: {POSTHOG_US_HOST}).",
        )
        # The previous revision evaluated flags for a specific distinct_id and group set;
        # the new revision lists flag definitions instead. These flags are kept as accepted
        # no-ops so existing callers and scripts do not break.
        parser.add_argument("--distinct_id", type=str, help=argparse.SUPPRESS)
        parser.add_argument("--organization", type=str, help=argparse.SUPPRESS)
        parser.add_argument("--project", type=str, help=argparse.SUPPRESS)
        parser.add_argument("--instance", type=str, help=argparse.SUPPRESS)
        parser.add_argument("--customer", type=str, help=argparse.SUPPRESS)

    def handle(self, *args, **options):
        try:
            sync_feature_flags_from_api(
                personal_api_key=options.get("personal_api_key"),
                project_id=options.get("project_id") or POSTHOG_US_PROJECT_ID,
                host=options.get("host") or POSTHOG_US_HOST,
                output_fn=self.stdout.write,
            )
        except requests.exceptions.RequestException as e:
            self.stdout.write(f"Failed to fetch feature flags: {str(e)}")
            raise
        except Exception as e:
            self.stdout.write(f"Error while syncing flags: {str(e)}")
            raise
