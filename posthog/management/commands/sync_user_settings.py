# ruff: noqa: T201 allow print statements

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import requests

from posthog.models import Team, User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.user_home_settings import UserHomeSettings


class Command(BaseCommand):
    help = "Sync user settings from PostHog cloud to local development environment"
    DEFAULT_CLOUD_TEAM_ID = 2

    # Fields to sync from User model
    USER_SYNC_FIELDS = [
        "theme_mode",
        "partial_notification_settings",
        "anonymize_data",
        "toolbar_mode",
        "hedgehog_config",
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--api-key",
            type=str,
            help="Personal API key for PostHog cloud (or set POSTHOG_PERSONAL_API_KEY env var)",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="https://us.posthog.com",
            help="PostHog host to sync from (default: https://us.posthog.com)",
        )
        parser.add_argument(
            "--local-email",
            type=str,
            help="Email of local user to sync to (defaults to first user; ignored if --all-users is set)",
        )
        parser.add_argument(
            "--all-users",
            action="store_true",
            help="Sync settings to all local users",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            help="Local team ID to sync team-specific settings to (defaults to user's current team)",
        )
        parser.add_argument(
            "--cloud-team-id",
            type=int,
            default=self.DEFAULT_CLOUD_TEAM_ID,
            help=f"Cloud team ID to fetch team-specific settings from (default: {self.DEFAULT_CLOUD_TEAM_ID})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be synced without making changes",
        )

    def handle(self, *args, **options):
        # Get API key from options or environment
        api_key = options.get("api_key") or os.environ.get("POSTHOG_PERSONAL_API_KEY")
        if not api_key:
            raise CommandError(
                "Personal API key required. Provide --api-key or set POSTHOG_PERSONAL_API_KEY environment variable.\n"
                "Get your API key from: https://us.posthog.com/settings/user-api-keys"
            )

        host = options["host"].rstrip("/")
        dry_run = options["dry_run"]
        all_users = options["all_users"]
        local_team_id = options.get("team_id")
        cloud_team_id = options["cloud_team_id"]

        if dry_run:
            print("[DRY RUN MODE] No changes will be made\n")

        # Determine which users to sync
        if all_users:
            local_users = list(User.objects.all().order_by("id"))
            if not local_users:
                print("No users found in local database")
                return
            print(f"Syncing settings to {len(local_users)} local user(s)\n")
        else:
            local_user = self._get_local_user(options.get("local_email"))
            if not local_user:
                return
            local_users = [local_user]

        # Fetch settings from cloud once
        try:
            cloud_user_settings = self._fetch_user_settings(host, api_key)
        except (requests.RequestException, Exception) as e:
            raise CommandError(f"Failed to fetch user settings from {host}: {e}")

        # Fetch team-specific settings from cloud once
        cloud_home_settings, cloud_shortcuts = self._fetch_team_settings(host, api_key, cloud_team_id)

        # Sync each user
        for user in local_users:
            if all_users:
                print(f"{'=' * 60}")
                print(f"Syncing user: {user.email} (ID: {user.id})")
                print(f"{'=' * 60}\n")

            self._sync_user(
                user,
                cloud_user_settings,
                local_team_id,
                cloud_team_id,
                cloud_home_settings,
                cloud_shortcuts,
                dry_run,
            )

            if all_users and user != local_users[-1]:
                print()  # Add spacing between users

        if not dry_run:
            print("\n✓ Settings synced successfully!")
        else:
            print("\n✓ Dry run completed (no changes made)")

    def _sync_user(
        self,
        local_user: User,
        cloud_user_settings: dict[str, Any],
        local_team_id: int | None,
        cloud_team_id: int,
        cloud_home_settings: dict[str, Any] | None,
        cloud_shortcuts: list[dict[str, Any]],
        dry_run: bool,
    ):
        """Sync settings for a single user"""
        # Get local team
        local_team = self._get_local_team(local_user, local_team_id)
        if not local_team:
            print(f"  ⚠ Skipping: No team found for user")
            return

        print(f"Syncing to local team: {local_team.name} (ID: {local_team.id})")
        print(f"Using cloud team ID: {cloud_team_id}\n")

        self._sync_user_settings(local_user, cloud_user_settings, dry_run)
        self._sync_home_settings(local_user, local_team, cloud_home_settings, dry_run)
        self._sync_shortcuts(local_user, local_team, cloud_shortcuts, dry_run)

    def _fetch_team_settings(
        self, host: str, api_key: str, team_id: int
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Fetch home settings and shortcuts for the specified cloud team"""
        try:
            cloud_home_settings = self._fetch_home_settings(host, api_key, team_id)
        except (requests.RequestException, Exception) as e:
            print(f"⚠ Warning: Failed to fetch cloud home settings for team {team_id}: {e}")
            cloud_home_settings = None

        try:
            cloud_shortcuts = self._fetch_shortcuts(host, api_key, team_id)
        except (requests.RequestException, Exception) as e:
            print(f"⚠ Warning: Failed to fetch cloud shortcuts for team {team_id}: {e}")
            cloud_shortcuts = []

        return cloud_home_settings, cloud_shortcuts

    def _get_local_user(self, email: str | None) -> User | None:
        """Get the local user to sync to"""
        if email:
            try:
                return User.objects.get(email=email)
            except User.DoesNotExist:
                print(f"Error: User with email {email} not found locally")
                return None
        else:
            user = User.objects.first()
            if not user:
                print("Error: No users found in local database")
                return None
            return user

    def _get_local_team(self, user: User, team_id: int | None) -> Team | None:
        """Get the local team to sync to"""
        if team_id:
            try:
                return Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                print(f"Error: Team with ID {team_id} not found locally")
                return None
        else:
            team = user.current_team or Team.objects.first()
            if not team:
                print("Error: No teams found in local database")
                return None
            return team

    def _fetch_user_settings(self, host: str, api_key: str) -> dict[str, Any]:
        """Fetch user settings from PostHog cloud API"""
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(f"{host}/api/users/@me/", headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def _fetch_home_settings(self, host: str, api_key: str, team_id: int) -> dict[str, Any] | None:
        """Fetch user home settings from PostHog cloud API"""
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(f"{host}/api/projects/{team_id}/user_home_settings/", headers=headers, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def _fetch_shortcuts(self, host: str, api_key: str, team_id: int) -> list[dict[str, Any]]:
        """Fetch shortcuts from PostHog cloud API"""
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(f"{host}/api/projects/{team_id}/file_system_shortcuts/", headers=headers, timeout=30)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        data = response.json()
        # API returns paginated response
        return data.get("results", [])

    def _sync_user_settings(self, local_user: User, cloud_settings: dict[str, Any], dry_run: bool):
        """Sync user preference fields"""
        print("Syncing user preferences:")
        changes_made = False

        for field in self.USER_SYNC_FIELDS:
            if field in cloud_settings:
                old_value = getattr(local_user, field)
                new_value = cloud_settings[field]

                if old_value != new_value:
                    changes_made = True
                    print(f"  {field}: {old_value} → {new_value}")
                    if not dry_run:
                        setattr(local_user, field, new_value)

        if not dry_run and changes_made:
            local_user.save()

        if not changes_made:
            print("  No changes needed")

    def _sync_home_settings(
        self, local_user: User, local_team: Team, cloud_settings: dict[str, Any] | None, dry_run: bool
    ):
        """Sync user home settings"""
        print("\nSyncing home settings:")

        if not cloud_settings:
            print("  No home settings found in cloud")
            return

        try:
            home_settings = UserHomeSettings.objects.get(user=local_user, team=local_team)
            action = "Updated"
        except UserHomeSettings.DoesNotExist:
            home_settings = UserHomeSettings(user=local_user, team=local_team)
            action = "Created"

        home_settings.tabs = cloud_settings.get("tabs", [])
        home_settings.homepage = cloud_settings.get("homepage", {})

        tab_count = len(home_settings.tabs)
        homepage_status = "set" if home_settings.homepage else "not set"

        print(f"  {action} home settings:")
        print(f"    - Pinned tabs: {tab_count}")
        print(f"    - Homepage: {homepage_status}")

        if not dry_run:
            home_settings.save()

    def _sync_shortcuts(self, local_user: User, local_team: Team, cloud_shortcuts: list[dict[str, Any]], dry_run: bool):
        """Sync file system shortcuts"""
        print("\nSyncing shortcuts:")

        if not cloud_shortcuts:
            print("  No shortcuts found in cloud")
            return

        # Delete existing shortcuts
        existing_count = FileSystemShortcut.objects.filter(user=local_user, team=local_team).count()
        if existing_count > 0:
            print(f"  Deleting {existing_count} existing shortcut(s)")
            if not dry_run:
                FileSystemShortcut.objects.filter(user=local_user, team=local_team).delete()

        # Create new shortcuts from cloud
        created_count = 0
        for shortcut_data in cloud_shortcuts:
            if not dry_run:
                FileSystemShortcut.objects.create(
                    user=local_user,
                    team=local_team,
                    path=shortcut_data["path"],
                    type=shortcut_data["type"],
                    ref=shortcut_data.get("ref"),
                    href=shortcut_data.get("href"),
                )
            created_count += 1

        print(f"  Created {created_count} shortcut(s)")
