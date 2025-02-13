from django.db import models
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema import FileSystemType
from posthog.models.utils import uuid7


class FileSystem(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid7)
    path = models.TextField()
    type = models.CharField(max_length=100)
    ref = models.CharField(max_length=100)
    href = models.TextField()
    meta = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.name


class UnfiledFileFinder:
    def __init__(self, team: Team, user: User):
        self.team = team
        self.user = user

    def collect_feature_flags(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import FeatureFlag

        flags = FeatureFlag.objects.filter(team=self.team, deleted=False)
        return [
            FileSystem(
                id=str(uuid7()),
                path=f"Unfiled/Feature Flags/{flag.name}",
                type=FileSystemType.FEATURE_FLAG,
                ref=str(flag.id),
                href="/feature_flags/" + str(flag.id),
                meta={
                    "created_at": str(flag.created_at),
                    "created_by": UserBasicSerializer(instance=flag.created_by).data if flag.created_by else None,
                },
            )
            for flag in flags
        ]

    def collect_experiments(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Experiment

        experiments = Experiment.objects.filter(team=self.team)
        return [
            FileSystem(
                id=str(uuid7()),
                path=f"Unfiled/Experiments/{experiment.name}",
                type=FileSystemType.EXPERIMENT,
                ref=str(experiment.id),
                href="/experiments/" + str(experiment.id),
                meta={
                    "created_at": str(experiment.created_at),
                    "created_by": UserBasicSerializer(instance=experiment.created_by).data
                    if experiment.created_by
                    else None,
                },
            )
            for experiment in experiments
        ]

    def collect_insights(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Insight

        insights = Insight.objects.filter(team=self.team, deleted=False)
        return [
            FileSystem(
                id=str(uuid7()),
                path=f"Unfiled/Insights/{insight.name}",
                type=FileSystemType.INSIGHT,
                ref=str(insight.short_id),
                href="/insights/" + str(insight.short_id),
                meta={
                    "created_at": str(insight.created_at),
                    "created_by": UserBasicSerializer(instance=insight.created_by).dat if insight.created_by else None,
                },
            )
            for insight in insights
        ]

    def collect_dashboards(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Dashboard

        dashboards = Dashboard.objects.filter(team=self.team, deleted=False)
        return [
            FileSystem(
                id=str(uuid7()),
                path=f"Unfiled/Dashboards/{dashboard.name}",
                type=FileSystemType.DASHBOARD,
                ref=str(dashboard.id),
                href="/dashboard/" + str(dashboard.id),
                meta={
                    "created_at": str(dashboard.created_at),
                    "created_by": UserBasicSerializer(instance=dashboard.created_by).data
                    if dashboard.created_by
                    else None,
                },
            )
            for dashboard in dashboards
        ]

    def collect_notebooks(self) -> list[FileSystem]:
        from posthog.api.shared import UserBasicSerializer
        from posthog.models import Notebook

        notebooks = Notebook.objects.filter(team=self.team, deleted=False)
        return [
            FileSystem(
                id=str(uuid7()),
                path=f"Unfiled/Notebooks/{notebook.title or 'Untitled'}",
                type=FileSystemType.NOTEBOOK,
                ref=str(notebook.id),
                href="/notebooks/" + str(notebook.id),
                meta={
                    "created_at": str(notebook.created_at),
                    "created_by": UserBasicSerializer(instance=notebook.created_by).data
                    if notebook.created_by
                    else None,
                },
            )
            for notebook in notebooks
        ]

    def collect(self) -> list[FileSystem]:
        return [
            *self.collect_feature_flags(),
            *self.collect_experiments(),
            *self.collect_insights(),
            *self.collect_dashboards(),
            *self.collect_notebooks(),
        ]


def get_unfiled_files(team: Team, user: User) -> list[FileSystem]:
    return UnfiledFileFinder(team, user).collect()


def get_filed_files(team: Team, user: User) -> list[FileSystem]:
    return FileSystem.objects.filter(team=team).order_by("path").all()
