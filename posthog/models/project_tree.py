from posthog.models import Team, User
from posthog.schema import ProjectTreeQuery, ProjectTreeQueryResponse


def get_project_tree(query: ProjectTreeQuery, team: Team, user: User) -> ProjectTreeQueryResponse:
    return ProjectTreeQueryResponse(tree=[])
