# ruff: noqa: T201 allow print statements

import re
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from django.core.management.base import BaseCommand

from posthog.management.desktop_feature_flag_sync import load_desktop_feature_flags
from posthog.models import Team, User

from products.feature_flags.backend.models.feature_flag import FeatureFlag

# These flags won't be enabled when syncing feature flags
# Turn these on for flags that heavily change the behavior and that you wouldn't like
# your fellow colleagues to see locally
#
# Examples of changes that should go here are authentication changes, big UI changes, debugging flags, etc.
INACTIVE_FLAGS = [
    "billing-forecasting-issues",
    "session-reset-on-load",
    "support-message-override",
    "halloween-override",
    "christmas-override",
    "control_support_login",
    "person-property-incident-annotation-jan-2026",
    "replay-exclude-from-hide-recordings-menu",
    "webhooks-denylist",
    "insight-horizontal-controls",
    "flagged-feature-indicator",
]

FRONTEND_FEATURE_FLAGS_PATH = Path("frontend/src/lib/constants.tsx")

FeatureFlagDefinition = str | list[str]


def parse_frontend_feature_flags(lines: Iterable[str]) -> dict[str, FeatureFlagDefinition]:
    flags: dict[str, FeatureFlagDefinition] = {}
    parsing_flags = False

    for line in lines:
        if parsing_flags:
            if "}" in line:
                parsing_flags = False
                continue

            try:
                flag = line.split("'")[1]
            except IndexError:
                continue

            multivariate_match = re.search(r"multivariate=([^\s/]+)", line)
            if not multivariate_match:
                flags[flag] = "boolean"
                continue

            variant_keys = [key.strip() for key in multivariate_match.group(1).split(",")]
            flags[flag] = ["control", "test"] if variant_keys == ["true"] else variant_keys
        elif "export const FEATURE_FLAGS" in line:
            parsing_flags = True

    return flags


def load_feature_flags() -> dict[str, FeatureFlagDefinition]:
    flags = parse_frontend_feature_flags(FRONTEND_FEATURE_FLAGS_PATH.read_text(encoding="utf_8").splitlines())
    flags.update(load_desktop_feature_flags())
    return flags


class Command(BaseCommand):
    help = "Add and enable all feature flags in frontend/src/lib/constants.tsx for all projects"

    def handle(self, *args, **options) -> None:
        flags = load_feature_flags()
        first_user = cast(User, User.objects.first())
        for team in Team.objects.all():
            self.sync_team_feature_flags(team, first_user, flags)

        print("Feature flag sync complete.")

    def sync_team_feature_flags(self, team: Team, first_user: User, flags: dict[str, FeatureFlagDefinition]) -> None:
        existing_flags = set(FeatureFlag.objects_including_soft_deleted.filter(team=team).values_list("key", flat=True))
        deleted_flags = set(
            FeatureFlag.objects_including_soft_deleted.filter(team=team, deleted=True).values_list("key", flat=True)
        )

        for flag, flag_type in flags.items():
            is_enabled = flag not in INACTIVE_FLAGS
            if flag in deleted_flags:
                self.restore_feature_flag(team, flag, is_enabled)
            elif flag not in existing_flags:
                self.create_feature_flag(team, first_user, flag, flag_type, is_enabled)

    def restore_feature_flag(self, team: Team, flag: str, is_enabled: bool) -> None:
        feature_flag = FeatureFlag.objects_including_soft_deleted.filter(team=team, key=flag).first()
        if not feature_flag:
            return

        feature_flag.deleted = False
        feature_flag.active = is_enabled
        feature_flag.save()
        print(f"Undeleted feature flag '{flag}' for team {team.id} {' - ' + team.name if team.name else ''}")

    def create_feature_flag(
        self, team: Team, first_user: User, flag: str, flag_type: FeatureFlagDefinition, is_enabled: bool
    ) -> None:
        if isinstance(flag_type, list):
            filters = {
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
            }
        else:
            filters = {"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {}}

        FeatureFlag.objects.create(
            team=team,
            name=flag,
            key=flag,
            created_by=first_user,
            active=is_enabled,
            filters=filters,
        )
        multivariate_details = f" (multivariate: {', '.join(flag_type)})" if isinstance(flag_type, list) else ""
        print(
            f"Created feature flag '{flag}' for team {team.id} {' - ' + team.name if team.name else ''}{multivariate_details}"
        )
