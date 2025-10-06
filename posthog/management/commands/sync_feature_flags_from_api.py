import json
from collections.abc import Callable

from django.core.management.base import BaseCommand

import requests

from posthog.models import FeatureFlag, Project, User
from posthog.ph_client import PH_US_API_KEY


def sync_feature_flags_from_api(
    distinct_id: str,
    groups: dict[str, str] | None = None,
    output_fn: Callable[[str], None] = print,
) -> None:
    """
    Fetch feature flags from the PostHog API and sync them to the database.

    Args:
        distinct_id: The distinct ID for which to evaluate feature flags
        groups: Optional dict of group types to IDs (customer, instance, organization, project)
        output_fn: Function to call for output (defaults to print, can use self.stdout.write for management commands)
    """
    if groups is None:
        groups = {
            "customer": "cus_IK2DWsWVn2ZM16",
            "instance": "https://us.posthog.com",
            "organization": "4dc8564d-bd82-1065-2f40-97f7c50f67cf",
            "project": "fc445b88-e2c4-488e-bb52-aa80cd7918c9",
        }

    output_fn(f"Fetching feature flags for {distinct_id}...")
    response = requests.post(
        "https://us.i.posthog.com/flags?v=2",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"api_key": PH_US_API_KEY, "distinct_id": distinct_id, "groups": groups}),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if "flags" not in data:
        output_fn("No flags found in API response")
        return

    first_user = User.objects.first()
    if not first_user:
        output_fn("No users found in database")
        return

    for project in Project.objects.all():
        output_fn(f"\nProcessing project {project.id} - {project.name or ''}")
        output_fn("=" * 50)

        existing_flags = FeatureFlag.objects.filter(team__project_id=project.id).values_list("key", flat=True)
        deleted_flags = FeatureFlag.objects.filter(team__project_id=project.id, deleted=True).values_list(
            "key", flat=True
        )

        enabled_flags = sum(1 for flag_data in data["flags"].values() if flag_data.get("enabled", False))
        total_flags = enabled_flags
        undeleted_count = 0
        created_count = 0
        activated_count = 0
        deactivated_count = 0
        unchanged_count = 0

        for flag_key, flag_data in data["flags"].items():
            is_enabled = flag_data.get("enabled", False)
            if flag_key in deleted_flags and is_enabled:
                ff = FeatureFlag.objects.get(team__project_id=project.id, key=flag_key)
                ff.deleted = False
                ff.active = True
                ff.save()
                output_fn(f"Undeleted feature flag '{flag_key}'")
                undeleted_count += 1

            elif flag_key not in existing_flags and is_enabled:
                FeatureFlag.objects.create(
                    team=project.teams.first(),
                    rollout_percentage=100,
                    name=flag_key,
                    key=flag_key,
                    created_by=first_user,
                    active=True,
                    filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {}},
                )
                output_fn(f"Created feature flag '{flag_key}'")
                created_count += 1

            else:
                ff = FeatureFlag.objects.filter(team__project_id=project.id, key=flag_key).first()
                if ff and ff.active != is_enabled:
                    ff.active = is_enabled
                    ff.save()
                    if is_enabled:
                        output_fn(f"Activated feature flag '{flag_key}'")
                        activated_count += 1
                    else:
                        output_fn(f"Deactivated feature flag '{flag_key}'")
                        deactivated_count += 1
                else:
                    unchanged_count += 1

        output_fn("\nProject Summary")
        output_fn("-" * 20)
        output_fn(f"Enabled flags from API: {total_flags}")
        output_fn(f"Existing: {len(existing_flags)}")
        output_fn(f"Undeleted: {undeleted_count}")
        output_fn(f"Created: {created_count}")
        output_fn(f"Activated: {activated_count}")
        output_fn(f"Deactivated: {deactivated_count}")
        output_fn(f"Unchanged: {unchanged_count}")
        output_fn(f"Total after sync: {len(existing_flags) + created_count}")


class Command(BaseCommand):
    help = "Sync feature flags by fetching them from the PostHog API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--distinct_id", type=str, required=True, help="The distinct ID for which to evaluate feature flags"
        )
        parser.add_argument("--organization", type=str, help="Organization ID")
        parser.add_argument("--project", type=str, help="Project ID")
        parser.add_argument("--instance", type=str, help="Instance ID")
        parser.add_argument("--customer", type=str, help="Customer ID")

    def handle(self, *args, **options):
        distinct_id = options["distinct_id"]

        groups = {}

        for group_type in ["customer", "instance", "organization", "project"]:
            if options.get(group_type):
                groups[group_type] = options[group_type]

        try:
            sync_feature_flags_from_api(distinct_id=distinct_id, groups=groups or None, output_fn=self.stdout.write)
        except requests.exceptions.RequestException as e:
            self.stdout.write(f"Failed to fetch feature flags: {str(e)}")
            raise
        except Exception as e:
            self.stdout.write(f"Error while syncing flags: {str(e)}")
            raise
