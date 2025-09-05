from django.core.management.base import BaseCommand
from posthog.models import FeatureFlag, Project, User
import json
import requests


class Command(BaseCommand):
    help = "Sync feature flags by fetching them from the PostHog API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--distinct_id", type=str, required=True, help="The distinct ID for which to evaluate feature flags"
        )

    def handle(self, *args, **options):
        distinct_id = options["distinct_id"]

        try:
            self.stdout.write(f"Fetching feature flags for {distinct_id}...")
            response = requests.post(
                "https://us.i.posthog.com/flags?v=2",
                headers={"Content-Type": "application/json"},
                data=json.dumps({"api_key": "sTMFPsFhdP1Ssg", "distinct_id": distinct_id}),
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            if "flags" not in data:
                self.stdout.write("No flags found in API response")
                return

            first_user = User.objects.first()
            if not first_user:
                self.stdout.write("No users found in database")
                return

            for project in Project.objects.all():
                self.stdout.write(f"Processing project {project.id} - {project.name or ''}")

                existing_flags = FeatureFlag.objects.filter(team__project_id=project.id).values_list("key", flat=True)

                deleted_flags = FeatureFlag.objects.filter(team__project_id=project.id, deleted=True).values_list(
                    "key", flat=True
                )

                for flag_key, flag_data in data["flags"].items():
                    is_enabled = flag_data.get("enabled", False)
                    if flag_key in deleted_flags:
                        ff = FeatureFlag.objects.filter(team__project_id=project.id, key=flag_key)[0]
                        ff.deleted = False
                        ff.active = is_enabled
                        ff.save()
                        self.stdout.write(f"Undeleted feature flag '{flag_key}'")

                    elif flag_key not in existing_flags:
                        FeatureFlag.objects.create(
                            team=project.teams.first(),
                            rollout_percentage=100,
                            name=flag_key,
                            key=flag_key,
                            created_by=first_user,
                            active=is_enabled,
                            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {}},
                        )
                        self.stdout.write(f"Created feature flag '{flag_key}'")

                    else:
                        ff = FeatureFlag.objects.filter(team__project_id=project.id, key=flag_key).first()
                        if ff and ff.active != is_enabled:
                            ff.active = is_enabled
                            ff.save()
                            self.stdout.write(f"Updated feature flag '{flag_key}' active status to {is_enabled}")

        except requests.exceptions.RequestException as e:
            self.stdout.write(f"Failed to fetch feature flags: {str(e)}")
            raise
        except Exception as e:
            self.stdout.write(f"Error while syncing flags: {str(e)}")
            raise
