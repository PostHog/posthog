from posthog.api.routing import RouterRegistry

from products.approvals.backend import api as approval_api


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"change_requests",
        approval_api.ChangeRequestViewSet,
        "project_change_requests",
        ["team_id"],
    )
    routers.projects.register(
        r"approval_policies",
        approval_api.ApprovalPolicyViewSet,
        "project_approval_policies",
        ["team_id"],
    )
