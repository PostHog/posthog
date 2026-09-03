import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from django.core.management.base import CommandError

from posthog.models import Team, User

from products.feature_flags.backend.models.feature_flag import FeatureFlag

DESKTOP_FEATURE_FLAG_KEYS_PATH = (
    Path(__file__).resolve().parents[2]
    / "products"
    / "desktop"
    / "packages"
    / "shared"
    / "src"
    / "feature-flag-keys.json"
)

DESKTOP_MULTIVARIATE_FLAGS = {"bedrock-llm-gateway": ["test", "control"]}


def load_desktop_feature_flags() -> dict[str, str | list[str]]:
    raw: object = json.loads(DESKTOP_FEATURE_FLAG_KEYS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CommandError("Desktop feature flag keys must be a JSON object.")

    flag_keys = cast(dict[object, object], raw)
    if not all(isinstance(name, str) and isinstance(key, str) for name, key in flag_keys.items()):
        raise CommandError("Desktop feature flag names and keys must be strings.")

    keys = cast(dict[str, str], flag_keys).values()
    return {key: DESKTOP_MULTIVARIATE_FLAGS.get(key, "boolean") for key in keys}


def sync_desktop_feature_flags(output_fn: Callable[[str], None]) -> None:
    flags = load_desktop_feature_flags()
    first_user = User.objects.first()
    if first_user is None:
        raise CommandError("No users found in the database.")

    for team in Team.objects.all():
        existing_flags = {
            flag.key: flag
            for flag in FeatureFlag.objects_including_soft_deleted.filter(team=team, key__in=flags.keys())
        }

        for key, flag_type in flags.items():
            existing_flag = existing_flags.get(key)
            if existing_flag is not None:
                if existing_flag.deleted:
                    existing_flag.deleted = False
                    existing_flag.active = True
                    existing_flag.save(update_fields=["deleted", "active"])
                    output_fn(f"Undeleted desktop feature flag '{key}' for team {team.id}")
                continue

            filters: dict[str, object] = {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {},
            }
            if isinstance(flag_type, list):
                filters["multivariate"] = {
                    "variants": [
                        {
                            "key": variant,
                            "name": variant.capitalize(),
                            "rollout_percentage": 100 if index == len(flag_type) - 1 else 0,
                        }
                        for index, variant in enumerate(flag_type)
                    ]
                }

            FeatureFlag.objects.create(
                team=team,
                name=key,
                key=key,
                created_by=first_user,
                active=True,
                filters=filters,
            )
            output_fn(f"Created desktop feature flag '{key}' for team {team.id}")

    output_fn("Desktop feature flag sync complete.")
