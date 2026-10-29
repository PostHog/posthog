from posthog.models.resource_transfer.visitors.action import ActionVisitor
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.cohort import CohortVisitor
from posthog.models.resource_transfer.visitors.dashboard import DashboardVisitor
from posthog.models.resource_transfer.visitors.dashboard_tile import DashboardTileVisitor
from posthog.models.resource_transfer.visitors.dashboard_widget import DashboardWidgetVisitor
from posthog.models.resource_transfer.visitors.early_access_feature import EarlyAccessFeatureVisitor
from posthog.models.resource_transfer.visitors.experiment import ExperimentVisitor
from posthog.models.resource_transfer.visitors.experiment_holdout import ExperimentHoldoutVisitor
from posthog.models.resource_transfer.visitors.experiment_saved_metric import ExperimentSavedMetricVisitor
from posthog.models.resource_transfer.visitors.experiment_to_saved_metric import ExperimentToSavedMetricVisitor
from posthog.models.resource_transfer.visitors.feature_flag import FeatureFlagVisitor
from posthog.models.resource_transfer.visitors.insight import InsightVisitor
from posthog.models.resource_transfer.visitors.project import ProjectVisitor
from posthog.models.resource_transfer.visitors.survey import SurveyActionsThroughVisitor, SurveyVisitor
from posthog.models.resource_transfer.visitors.team import TeamVisitor
from posthog.models.resource_transfer.visitors.text import TextVisitor
from posthog.models.resource_transfer.visitors.user import UserVisitor

# Visitors for models that a product owns are declared by the product, in
# `backend/resource_transfer/`. See posthog/models/resource_transfer/registry.py.
CORE_VISITORS: tuple[type[ResourceTransferVisitor], ...] = (
    ActionVisitor,
    CohortVisitor,
    DashboardVisitor,
    DashboardTileVisitor,
    DashboardWidgetVisitor,
    EarlyAccessFeatureVisitor,
    ExperimentVisitor,
    ExperimentHoldoutVisitor,
    ExperimentSavedMetricVisitor,
    ExperimentToSavedMetricVisitor,
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
    "ExperimentHoldoutVisitor",
    "ExperimentSavedMetricVisitor",
    "ExperimentToSavedMetricVisitor",
    "ExperimentVisitor",
    "FeatureFlagVisitor",
    "InsightVisitor",
    "SurveyVisitor",
    "SurveyActionsThroughVisitor",
    "ProjectVisitor",
    "TeamVisitor",
    "TextVisitor",
    "UserVisitor",
]
