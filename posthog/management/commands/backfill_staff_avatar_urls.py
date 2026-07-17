import logging
import unicodedata
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandParser

import requests

from posthog.models import User, UserPersonalization

logger = logging.getLogger(__name__)

# posthog.com is a Gatsby site with no team API: the roster ships as a
# build-time static-query artifact. The hash is a content hash of the site's
# GraphQL query, so when it drifts we rescan the hashes the /people page
# manifest declares.
PAGE_DATA_BASE = "https://posthog.com/page-data"
KNOWN_TEAM_QUERY_HASH = "2290419275"
STAFF_EMAIL_DOMAIN = "posthog.com"
REQUEST_TIMEOUT_SECONDS = 15


def _fetch_json(url: str) -> Optional[Any]:
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code != 200:
            return None
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def _parse_profiles(payload: Any) -> list[dict[str, Any]]:
    members = ((payload or {}).get("data") or {}).get("team", {}).get("teamMembers")
    if not isinstance(members, list):
        return []
    profiles = []
    for member in members:
        if not isinstance(member, dict) or not isinstance(member.get("firstName"), str):
            continue
        avatar = member.get("avatar") or {}
        url = avatar.get("url") if isinstance(avatar, dict) else None
        profiles.append(
            {
                "first_name": member["firstName"],
                "last_name": member.get("lastName") or "",
                "avatar_url": url if isinstance(url, str) else None,
            }
        )
    return profiles


def fetch_team_profiles() -> list[dict[str, Any]]:
    profiles = _parse_profiles(_fetch_json(f"{PAGE_DATA_BASE}/sq/d/{KNOWN_TEAM_QUERY_HASH}.json"))
    if profiles:
        return profiles
    manifest = _fetch_json(f"{PAGE_DATA_BASE}/people/page-data.json") or {}
    for query_hash in manifest.get("staticQueryHashes") or []:
        if not isinstance(query_hash, str) or query_hash == KNOWN_TEAM_QUERY_HASH:
            continue
        profiles = _parse_profiles(_fetch_json(f"{PAGE_DATA_BASE}/sq/d/{query_hash}.json"))
        if profiles:
            return profiles
    return []


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(stripped.lower().split())


def build_avatar_index(profiles: list[dict[str, Any]]) -> dict[str, Optional[str]]:
    # Full-name key -> avatar URL; two different people sharing a name makes
    # the key ambiguous (None) so nobody gets a namesake's photo.
    index: dict[str, Optional[str]] = {}
    for profile in profiles:
        if not profile["avatar_url"]:
            continue
        key = normalize_name(f"{profile['first_name']} {profile['last_name']}")
        if key in index and index[key] != profile["avatar_url"]:
            index[key] = None
        else:
            index[key] = profile["avatar_url"]
    return index


class Command(BaseCommand):
    help = (
        "Backfill UserPersonalization.avatar_url for PostHog staff accounts from the public "
        "posthog.com/people roster, matched by full name. Ambiguous names and accounts without a "
        "roster match are skipped. Idempotent; skips users who already have an avatar unless "
        "--overwrite."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report matches without writing.")
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Also update users who already have an avatar set.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        overwrite: bool = options["overwrite"]

        profiles = fetch_team_profiles()
        if not profiles:
            self.stderr.write(self.style.ERROR("Could not fetch the posthog.com team roster; aborting."))
            return
        index = build_avatar_index(profiles)
        self.stdout.write(f"Fetched {len(profiles)} roster profiles ({len(index)} name keys).")

        users = User.objects.filter(email__iendswith=f"@{STAFF_EMAIL_DOMAIN}", is_active=True).select_related(
            "personalization"
        )

        updated = 0
        ambiguous = 0
        unmatched = 0
        for user in users.iterator():
            existing = getattr(user, "personalization", None)
            if existing and existing.avatar_url and not overwrite:
                continue
            # Staff accounts sometimes hold the full name in first_name with
            # last_name empty, so match on the combined display name.
            key = normalize_name(f"{user.first_name} {user.last_name}")
            if key not in index:
                unmatched += 1
                continue
            avatar_url = index[key]
            if avatar_url is None:
                ambiguous += 1
                self.stdout.write(f"  ambiguous roster name for {user.email}; skipping")
                continue
            if existing and existing.avatar_url == avatar_url:
                continue
            self.stdout.write(f"  {user.email} -> {avatar_url}")
            if not dry_run:
                UserPersonalization.objects.update_or_create(user=user, defaults={"avatar_url": avatar_url})
            updated += 1

        prefix = "[DRY RUN] Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{prefix} {updated} users ({ambiguous} ambiguous, {unmatched} without a roster match).")
        )
