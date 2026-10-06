from django.db import connection, models, transaction

from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system import FileSystem, join_path
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDModel


class FileSystemHomeFolder(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False)
    # Keep the initialization record after deletion so opening the sidebar never recreates the folder.
    folder = models.OneToOneField("posthog.FileSystem", on_delete=models.SET_NULL, null=True, db_constraint=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "user"], name="posthog_unique_home_folder_user")]

    @classmethod
    def ensure_for_user(cls, *, team: Team, user: User) -> FileSystem | None:
        team = team.parent_team or team
        homes = cls.objects.for_team(team.pk)
        existing = homes.select_related("folder").filter(user=user).first()
        if existing is not None:
            return existing.folder

        with transaction.atomic():
            # Serialize name allocation across users without locking the hot Team row.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"home-folder:{team.pk}"])
            existing = homes.select_related("folder").filter(user=user).first()
            if existing is not None:
                return existing.folder

            name = user.first_name.strip() or "My home"
            # Shortcut refs allow 100 characters, including escaping and a collision suffix.
            while len(join_path(["Users", name])) > 90:
                name = name[:-1]
            entries = FileSystem.objects.filter(surface_q(DEFAULT_SURFACE), team=team)
            suffix = 0
            while True:
                folder_name = name if suffix == 0 else f"{name} ({suffix})"
                folder_path = join_path(["Users", folder_name])
                occupied = entries.filter(path=folder_path)
                own_folder = occupied.filter(type="folder", created_by=user).exclude(shortcut=True).first()
                if own_folder is not None and not homes.filter(folder=own_folder).exists():
                    homes.create(team=team, user=user, folder=own_folder)
                    return own_folder
                if not occupied.exists():
                    break
                suffix += 1

            if not entries.filter(path="Users", type="folder").exists():
                FileSystem.objects.create(
                    team=team, path="Users", depth=1, type="folder", created_by=user, surface=DEFAULT_SURFACE
                )
            folder = FileSystem.objects.create(
                team=team,
                path=folder_path,
                depth=2,
                type="folder",
                created_by=user,
                surface=DEFAULT_SURFACE,
            )
            homes.create(team=team, user=user, folder=folder)
            FileSystemShortcut.objects.create(
                team=team,
                user=user,
                path=join_path([folder_name]),
                type="folder",
                ref=folder.path,
                order=-1,
                surface=DEFAULT_SURFACE,
            )
            return folder
