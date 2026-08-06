from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request

from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.api.insight import InsightViewSet
from products.product_analytics.backend.models.insight import Insight


class CanEditInsight(BasePermission):
    message = "This insight is on a dashboard that can only be edited by its owner, team members invited to editing the dashboard, and project admins."

    def has_object_permission(self, request: Request, view, insight: Insight) -> bool:
        if request.method in SAFE_METHODS:
            return True

        return view.user_permissions.insight(insight).effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT


class EnterpriseInsightsViewSet(InsightViewSet):
    permission_classes = [CanEditInsight]
