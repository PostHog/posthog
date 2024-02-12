from typing import Dict, cast

from django.core.management.base import BaseCommand

from posthog.models import FeatureFlag, Team, User

INACTIVE_FLAGS = ["cloud-announcement", "session-reset-on-load", "posthog-3000-nav"]


class Command(BaseCommand):
    help = "Add and enable all feature flags in frontend/src/lib/constants.tsx for all teams"

    def handle(self, *args, **options):
        flags: Dict[str, str] = {}
        with open("frontend/src/lib/constants.tsx", "r", encoding="utf_8") as f:
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
        for team in Team.objects.all():
            existing_flags = FeatureFlag.objects.filter(team=team).values_list("key", flat=True)
            deleted_flags = FeatureFlag.objects.filter(team=team, deleted=True).values_list("key", flat=True)
            for flag in flags.keys():
                flag_type = flags[flag]
                is_enabled = flag not in INACTIVE_FLAGS

                if flag in deleted_flags:
                    ff = FeatureFlag.objects.filter(team=team, key=flag)[0]
                    ff.deleted = False
                    ff.active = is_enabled
                    ff.save()
                    print(f"Undeleted feature flag '{flag} for team {team.id} {' - ' + team.name if team.name else ''}")
                elif flag not in existing_flags:
                    if flag_type == "multivariate":
                        FeatureFlag.objects.create(
                            team=team,
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
                            team=team,
                            rollout_percentage=100,
                            name=flag,
                            key=flag,
                            created_by=first_user,
                            active=is_enabled,
                        )
                    print(f"Created feature flag '{flag} for team {team.id} {' - ' + team.name if team.name else ''}")
