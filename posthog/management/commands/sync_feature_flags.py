# ruff: noqa: T201 allow print statements

import re
from typing import cast

from django.core.management.base import BaseCommand

from posthog.models import FeatureFlag, Team, User

# These flags won't be enabled when syncing feature flags
# Turn these on for flags that heavily change the behavior and that you wouldn't like
# your fellow colleagues to see locally
#
# Examples of changes that should go here are authentication changes, big UI changes, debugging flags, etc.
INACTIVE_FLAGS = [
    "billing-forecasting-issues",
    "session-reset-on-load",
    "support-message-override",
    "usage-spend-dashboards",
    "halloween-override",
    "christmas-override",
    "control_support_login",
    "person-property-incident-annotation-jan-2026",
    "replay-exclude-from-hide-recordings-menu",
    "webhooks-denylist",
    "insight-horizontal-controls",
    "flagged-feature-indicator",
    "ai-only-mode",
    "ai-first",
]


class Command(BaseCommand):
    help = "Add and enable all feature flags in frontend/src/lib/constants.tsx for all projects"

    def handle(self, *args, **options):
        flags: dict[str, str | list[str]] = {}
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
                            multivariate_match = re.search(r"multivariate=([^\s/]+)", line)
                            if multivariate_match:
                                variant_keys = [key.strip() for key in multivariate_match.group(1).split(",")]
                                if len(variant_keys) == 1 and variant_keys[0] == "true":
                                    flags[flag] = ["control", "test"]
                                else:
                                    flags[flag] = cast(list[str], variant_keys)
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
                    print(
                        f"Undeleted feature flag '{flag}' for team {team.id} {' - ' + team.name if team.name else ''}"
                    )
                elif flag not in existing_flags:
                    if isinstance(flag_type, list):
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
                                            "key": key,
                                            "name": key.capitalize(),
                                            "rollout_percentage": 100 if index == len(flag_type) - 1 else 0,
                                        }
                                        for index, key in enumerate(flag_type)
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
                            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {}},
                        )

                    print(
                        f"Created feature flag '{flag} for team {team.id} {' - ' + team.name if team.name else ''}{f' (multivariate: {", ".join(flag_type)})' if isinstance(flag_type, list) else ''}"
                    )
