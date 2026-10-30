from posthog.models.resource_transfer.visitors.action import ActionVisitor
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.cohort import CohortVisitor
from posthog.models.resource_transfer.visitors.dashboard import DashboardVisitor
from posthog.models.resource_transfer.visitors.dashboard_tile import DashboardTileVisitor
from posthog.models.resource_transfer.visitors.dashboard_widget import DashboardWidgetVisitor
from posthog.models.resource_transfer.visitors.early_access_feature import EarlyAccessFeatureVisitor
from posthog.models.resource_transfer.visitors.feature_flag import FeatureFlagVisitor
from posthog.models.resource_transfer.visitors.insight import InsightVisitor
from posthog.models.resource_transfer.visitors.project import ProjectVisitor
from posthog.models.resource_transfer.visitors.survey import SurveyActionsThroughVisitor, SurveyVisitor
from posthog.models.resource_transfer.visitors.team import TeamVisitor
from posthog.models.resource_transfer.visitors.text import TextVisitor
from posthog.models.resource_transfer.visitors.user import UserVisitor

# A product can declare the visitors for its own models in its `backend/resource_transfer/`
# package instead of here. See posthog/models/resource_transfer/registry.py.
CORE_VISITORS: tuple[type[ResourceTransferVisitor], ...] = (
    ActionVisitor,
    CohortVisitor,
    DashboardVisitor,
    DashboardTileVisitor,
    DashboardWidgetVisitor,
    EarlyAccessFeatureVisitor,
    FeatureFlagVisitor,
    InsightVisitor,
    ProjectVisitor,
    SurveyVisitor,
    SurveyActionsThroughVisitor,
    TeamVisitor,
    TextVisitor,
    UserVisitor,
)

__all__ = [
    "CORE_VISITORS",
    "ResourceTransferVisitor",
    "ActionVisitor",
    "CohortVisitor",
    "DashboardVisitor",
    "DashboardTileVisitor",
    "DashboardWidgetVisitor",
    "EarlyAccessFeatureVisitor",
    "FeatureFlagVisitor",
    "InsightVisitor",
    "SurveyVisitor",
    "SurveyActionsThroughVisitor",
    "ProjectVisitor",
    "TeamVisitor",
    "TextVisitor",
    "UserVisitor",
]
