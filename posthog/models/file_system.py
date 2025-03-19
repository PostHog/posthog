from django.db import models
from django.db.models import Exists, OuterRef, CharField
from django.db.models.functions import Cast
from typing import Optional

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import uuid7


class FileSystem(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid7)
    path = models.TextField()
    depth = models.IntegerField(null=True, blank=True)
    type = models.CharField(max_length=100, blank=True)
    ref = models.CharField(max_length=100, null=True, blank=True)
    href = models.TextField(null=True, blank=True)
    meta = models.JSONField(default=dict, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.path


class UnfiledFileSaver:
    """
    Saves new FileSystem rows for items (FeatureFlags, Experiments, Insights, Dashboards, Notebooks, etc.)
    that haven't yet been placed in the FileSystem. Also ensures each path is unique,
    appending a numeric suffix if necessary.
    """

    def __init__(self, team: Team, user: User):
        self.team = team
        self.user = user
        self._in_memory_paths: set[str] = set()

    def save_unfiled_feature_flags(self) -> list[FileSystem]:
        """
        Find all FeatureFlags in this team that aren't yet represented in FileSystem (via type=FEATURE_FLAG, ref=<id>),
        create new FileSystem rows for them, and return the list of newly created FileSystem rows.
        """
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import FeatureFlag

        unsaved_qs = (
            FeatureFlag.objects.filter(team=self.team, deleted=False)
            .annotate(id_str=Cast("id", output_field=CharField()))
            .annotate(
                already_saved=Exists(
                    FileSystem.objects.filter(
                        team=self.team,
                        type="feature_flag",
                        ref=OuterRef("id_str"),
                    )
                )
            )
            .filter(already_saved=False)
        )

        new_files = []
        for flag in unsaved_qs:
            path = self._generate_unique_path("Unfiled/Feature Flags", flag.name or "Untitled")

            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type="feature_flag",
                    ref=str(flag.id),  # store the ID as a string
                    href=f"/feature_flags/{flag.id}",
                    meta={
                        "created_at": str(flag.created_at),
                        "created_by": UserBasicSerializer(flag.created_by).data if flag.created_by else None,
                    },
                    created_by=self.user,
                )
            )

        FileSystem.objects.bulk_create(new_files)
        return new_files

    def save_unfiled_experiments(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Experiment

        unsaved_qs = (
            Experiment.objects.filter(team=self.team)
            .annotate(id_str=Cast("id", output_field=CharField()))
            .annotate(
                already_saved=Exists(
                    FileSystem.objects.filter(
                        team=self.team,
                        type="experiment",
                        ref=OuterRef("id_str"),
                    )
                )
            )
            .filter(already_saved=False)
        )

        new_files = []
        for experiment in unsaved_qs:
            path = self._generate_unique_path("Unfiled/Experiments", experiment.name or "Untitled")

            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type="experiment",
                    ref=str(experiment.id),
                    href=f"/experiments/{experiment.id}",
                    meta={
                        "created_at": str(experiment.created_at),
                        "created_by": UserBasicSerializer(experiment.created_by).data
                        if experiment.created_by
                        else None,
                    },
                    created_by=self.user,
                )
            )

        FileSystem.objects.bulk_create(new_files)
        return new_files

    def save_unfiled_insights(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Insight

        unsaved_qs = (
            Insight.objects.filter(team=self.team, deleted=False, saved=True)
            .annotate(
                already_saved=Exists(
                    FileSystem.objects.filter(
                        team=self.team,
                        type="insight",
                        ref=OuterRef("short_id"),
                    )
                )
            )
            .filter(already_saved=False)
        )

        new_files = []
        for insight in unsaved_qs:
            path = self._generate_unique_path("Unfiled/Insights", insight.name or "Untitled")

            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type="insight",
                    ref=str(insight.short_id),  # short_id is a string
                    href=f"/insights/{insight.short_id}",
                    meta={
                        "created_at": str(insight.created_at),
                        "created_by": UserBasicSerializer(insight.created_by).data if insight.created_by else None,
                    },
                    created_by=self.user,
                )
            )

        FileSystem.objects.bulk_create(new_files)
        return new_files

    def save_unfiled_dashboards(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Dashboard

        unsaved_qs = (
            Dashboard.objects.filter(team=self.team, deleted=False)
            .exclude(creation_mode="template")
            .annotate(id_str=Cast("id", output_field=CharField()))
            .annotate(
                already_saved=Exists(
                    FileSystem.objects.filter(
                        team=self.team,
                        type="dashboard",
                        ref=OuterRef("id_str"),
                    )
                )
            )
            .filter(already_saved=False)
        )

        new_files = []
        for dashboard in unsaved_qs:
            path = self._generate_unique_path("Unfiled/Dashboards", dashboard.name or "Untitled")

            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type="dashboard",
                    ref=str(dashboard.id),
                    href=f"/dashboard/{dashboard.id}",
                    meta={
                        "created_at": str(dashboard.created_at),
                        "created_by": UserBasicSerializer(dashboard.created_by).data if dashboard.created_by else None,
                    },
                    created_by=self.user,
                )
            )

        FileSystem.objects.bulk_create(new_files)
        return new_files

    def save_unfiled_notebooks(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Notebook

        unsaved_qs = (
            Notebook.objects.filter(team=self.team, deleted=False)
            .annotate(id_str=Cast("id", output_field=CharField()))
            .annotate(
                already_saved=Exists(
                    FileSystem.objects.filter(
                        team=self.team,
                        type="notebook",
                        ref=OuterRef("id_str"),
                    )
                )
            )
            .filter(already_saved=False)
        )

        new_files = []
        for notebook in unsaved_qs:
            title = notebook.title or "Untitled"
            path = self._generate_unique_path("Unfiled/Notebooks", title)

            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type="notebook",
                    ref=str(notebook.id),
                    href=f"/notebooks/{notebook.id}",
                    meta={
                        "created_at": str(notebook.created_at),
                        "created_by": UserBasicSerializer(notebook.created_by).data if notebook.created_by else None,
                    },
                    created_by=self.user,
                )
            )

        FileSystem.objects.bulk_create(new_files)
        return new_files

    def _generate_unique_path(self, base_folder: str, name: str) -> str:
        """
        Given a base folder (e.g. 'Unfiled/Feature Flags') and an item name,
        build a path that does not yet exist for this team.
        For instance:
            'Unfiled/Feature Flags/Flag A'
            If that exists, we try:
            'Unfiled/Feature Flags/Flag A (1)', etc.

        Also checks self._in_memory_paths for collisions
        among newly generated paths in this run.
        """
        desired = f"{base_folder}/{escape_path(name)}"
        path = desired
        index = 1

        # We loop until we find a path that is not used in the DB or in this run
        while path in self._in_memory_paths or FileSystem.objects.filter(team=self.team, path=path).exists():
            path = f"{desired} ({index})"
            index += 1

        # Mark it as used within this run
        self._in_memory_paths.add(path)
        return path

    def save_all_unfiled(self) -> list[FileSystem]:
        """
        Convenience method to save all unfiled items of every supported type
        and return the full list of newly created FileSystem objects.
        """
        created = []
        created += self.save_unfiled_feature_flags()
        created += self.save_unfiled_experiments()
        created += self.save_unfiled_insights()
        created += self.save_unfiled_dashboards()
        created += self.save_unfiled_notebooks()
        # TODO: add other object types here (annotations, etc.)
        return created


def save_unfiled_files(team: Team, user: User, file_type: Optional[str] = None) -> list[FileSystem]:
    """
    Public helper to save any "unfiled" items of a particular type (FeatureFlag, Dashboard, etc.)
    or, if file_type is None, for all supported types.
    """
    saver = UnfiledFileSaver(team, user)

    if file_type is None:
        return saver.save_all_unfiled()
    elif file_type == "feature_flag":
        return saver.save_unfiled_feature_flags()
    elif file_type == "experiment":
        return saver.save_unfiled_experiments()
    elif file_type == "insight":
        return saver.save_unfiled_insights()
    elif file_type == "dashboard":
        return saver.save_unfiled_dashboards()
    elif file_type == "notebook":
        return saver.save_unfiled_notebooks()

    # If it's an unknown/unsupported file type, return empty
    return []


def split_path(path: str) -> list[str]:
    segments = []
    current = ""
    i = 0
    while i < len(path):
        # If we encounter a backslash, and the next char is either / or \
        if path[i] == "\\" and i < len(path) - 1 and path[i + 1] in ["/", "\\"]:
            current += path[i + 1]
            i += 2
            continue
        elif path[i] == "/":
            segments.append(current)
            current = ""
        else:
            current += path[i]
        i += 1

    # Push any remaining part of the path into segments
    segments.append(current)

    # Filter out empty segments
    return [s for s in segments if s != ""]


def escape_path(path: str) -> str:
    # Replace backslash with double-backslash, and forward slash with backslash-slash
    path = path.replace("\\", "\\\\")
    path = path.replace("/", "\\/")
    return path


def join_path(paths: list[str]) -> str:
    # Join all segments using '/', while escaping each segment
    return "/".join(escape_path(segment) for segment in paths)
