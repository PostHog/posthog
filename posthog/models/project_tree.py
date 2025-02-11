from posthog.api.shared import UserBasicSerializer
from posthog.models import Team, User, FeatureFlag, Experiment, Insight, Dashboard, Notebook
from posthog.schema import ProjectTreeQuery, ProjectTreeQueryResponse, ProjectTreeItem, ProjectTreeItemType
from posthog.models.utils import uuid7


class ProjectTreeBuilder:
    def __init__(self, team: Team, user: User):
        self.team = team
        self.user = user

    def collect_feature_flags(self) -> list[ProjectTreeItem]:
        flags = FeatureFlag.objects.filter(team=self.team, deleted=False)
        return [
            ProjectTreeItem(
                id=str(uuid7()),
                name=flag.name,
                folder="Unfiled/Feature Flags",
                type=ProjectTreeItemType.FEATURE_FLAG,
                href="/feature_flags/" + str(flag.id),
                meta={
                    "created_at": str(flag.created_at),
                    "created_by": UserBasicSerializer(instance=flag.created_by).data if flag.created_by else None,
                },
            )
            for flag in flags
        ]

    def collect_experiments(self):
        experiments = Experiment.objects.filter(team=self.team)
        return [
            ProjectTreeItem(
                id=str(uuid7()),
                name=experiment.name,
                folder="Unfiled/Experiments",
                type=ProjectTreeItemType.EXPERIMENT,
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

    def collect_insights(self):
        insights = Insight.objects.filter(team=self.team, deleted=False)
        return [
            ProjectTreeItem(
                id=str(uuid7()),
                name=insight.name,
                folder="Unfiled/Insights",
                type=ProjectTreeItemType.INSIGHT,
                href="/insights/" + str(insight.id),
                meta={
                    "created_at": str(insight.created_at),
                    "created_by": UserBasicSerializer(instance=insight.created_by).dat if insight.created_by else None,
                },
            )
            for insight in insights
        ]

    def collect_dashboards(self):
        dashboards = Dashboard.objects.filter(team=self.team, deleted=False)
        return [
            ProjectTreeItem(
                id=str(uuid7()),
                name=dashboard.name,
                folder="Unfiled/Dashboards",
                type=ProjectTreeItemType.DASHBOARD,
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

    def collect_notebooks(self):
        notebooks = Notebook.objects.filter(team=self.team, deleted=False)
        return [
            ProjectTreeItem(
                id=str(uuid7()),
                name=notebook.title or "Untitled",
                folder="Unfiled/Notebooks",
                type=ProjectTreeItemType.NOTEBOOK,
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

    def build(self, query: ProjectTreeQuery) -> ProjectTreeQueryResponse:
        tree: list[ProjectTreeItem] = [
            *self.collect_feature_flags(),
            *self.collect_experiments(),
            *self.collect_insights(),
            *self.collect_dashboards(),
            *self.collect_notebooks(),
        ]
        return ProjectTreeQueryResponse(results=tree)


def get_project_tree(query: ProjectTreeQuery, team: Team, user: User) -> ProjectTreeQueryResponse:
    return ProjectTreeBuilder(team, user).build(query)
