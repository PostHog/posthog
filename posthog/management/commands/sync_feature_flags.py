# ruff: noqa: T201 allow print statements

from typing import cast

from django.core.management.base import BaseCommand

from posthog.models import FeatureFlag, Project, User

# These flags won't be enabled when syncing feature flags
# Turn these on for flags that heavily change the behavior and that you wouldn't like
# your fellow colleagues to see locally
#
# Examples of changes that should go here are authentication changes, big UI changes, etc.
INACTIVE_FLAGS = [
    "session-reset-on-load",
    "posthog-3000-nav",
    "insight-horizontal-controls",
    "flagged-feature-indicator",
]


class Command(BaseCommand):
    help = "Add and enable all feature flags in frontend/src/lib/constants.tsx for all projects"

    def handle(self, *args, **options):
        flags: dict[str, str] = {}
        with open("frontend/src/lib/constants.tsx", encoding="utf_8") as f:
            lines = f.readlines()
            parsing_flags = False
            for line in lines:
                if parsing_flags:
                    if "}" in line:
                        parsing_flags = False
                    else:
                        try:
                            flag = line.split("'")[1]
                            if flag.endswith("_EXPERIMENT") or "multivariate" in line:
                                flags[flag] = "multivariate"
                            else:
                                flags[flag] = "boolean"
                        except IndexError:
                            pass

                elif "export const FEATURE_FLAGS" in line:
                    parsing_flags = True

        first_user = cast(User, User.objects.first())
        for project in Project.objects.all():
            existing_flags = FeatureFlag.objects.filter(team__project_id=project.id).values_list("key", flat=True)
            deleted_flags = FeatureFlag.objects.filter(team__project_id=project.id, deleted=True).values_list(
                "key", flat=True
            )
            for flag in flags.keys():
                flag_type = flags[flag]
                is_enabled = flag not in INACTIVE_FLAGS

                if flag in deleted_flags:
                    ff = FeatureFlag.objects.filter(team__project_id=project.id, key=flag)[0]
                    ff.deleted = False
                    ff.active = is_enabled
                    ff.save()
                    print(
                        f"Undeleted feature flag '{flag} for project {project.id} {' - ' + project.name if project.name else ''}"
                    )
                elif flag not in existing_flags:
                    if flag_type == "multivariate":
                        FeatureFlag.objects.create(
                            team=project.teams.first(),
                            rollout_percentage=100,
                            name=flag,
                            key=flag,
                            created_by=first_user,
                            active=is_enabled,
                            filters={
                                "groups": [{"properties": [], "rollout_percentage": None}],
                                "multivariate": {
                                    "variants": [
                                        {
                                            "key": "control",
                                            "name": "Control",
                                            "rollout_percentage": 0,
                                        },
                                        {
                                            "key": "test",
                                            "name": "Test",
                                            "rollout_percentage": 100,
                                        },
                                    ]
                                },
                            },
                        )
                    else:
                        FeatureFlag.objects.create(
                            team=project.teams.first(),
                            rollout_percentage=100,
                            name=flag,
                            key=flag,
                            created_by=first_user,
                            active=is_enabled,
                            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {}},
                        )
                    print(
                        f"Created feature flag '{flag} for project {project.id} {' - ' + project.name if project.name else ''}"
                    )
