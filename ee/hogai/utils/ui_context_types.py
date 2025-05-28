from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, RootModel


class InsightContextForMax(BaseModel):
    """Context for a single insight, to be used by Max"""

    id: Union[str, int]
    name: Optional[str] = None
    description: Optional[str] = None
    query: dict[str, Any]  # The actual query node, e.g., TrendsQuery, HogQLQuery
    insight_type: Optional[str] = None  # Type of insight, e.g., NodeKind.TrendsQuery


class DashboardDisplayContext(BaseModel):
    """Context for a dashboard being viewed"""

    id: Union[str, int]
    name: Optional[str] = None
    description: Optional[str] = None


class MultiInsightContainer(RootModel[dict[str, InsightContextForMax]]):
    """Container for multiple active insights, typically on a dashboard"""


class MaxProductInfo(BaseModel):
    """Simplified product information for Max context"""

    type: str
    name: str
    description: str
    is_used: bool  # current_usage > 0
    has_exceeded_limit: bool
    current_usage: Optional[int] = None
    usage_limit: Optional[int] = None
    percentage_usage: float


class MaxAddonInfo(BaseModel):
    """Simplified addon information for Max context"""

    type: str
    name: str
    description: str
    is_used: bool  # current_usage > 0
    has_exceeded_limit: bool
    current_usage: int
    usage_limit: Optional[int] = None
    percentage_usage: Optional[float] = None
    included_with_main_product: Optional[bool] = None


class TrialInfo(BaseModel):
    """Trial information"""

    is_active: bool
    expires_at: Optional[str] = None
    target: Optional[str] = None


class BillingPeriod(BaseModel):
    """Billing period information"""

    current_period_start: str
    current_period_end: str
    interval: Literal["month", "year"]


class GlobalBillingContext(BaseModel):
    """Comprehensive billing context for Max"""

    # Overall billing status
    has_active_subscription: bool
    subscription_level: Literal["free", "paid", "custom"]
    billing_plan: Optional[str] = None
    is_deactivated: Optional[bool] = None

    # Products and addons information
    products: list[MaxProductInfo]
    addons: list[MaxAddonInfo]  # flattened from all products

    # Usage summary
    total_current_amount_usd: Optional[str] = None
    total_projected_amount_usd: Optional[str] = None

    # Trial information
    trial: Optional[TrialInfo] = None

    # Billing period
    billing_period: Optional[BillingPeriod] = None

    pass


class MaxNavigationContext(BaseModel):
    """Navigation context for Max"""

    path: str
    page_title: Optional[str] = None


class GlobalInfo(BaseModel):
    """General information that's always good to have, if available"""

    navigation: Optional[MaxNavigationContext] = None
    billing: Optional[GlobalBillingContext] = None


class MaxContextShape(BaseModel):
    """The main shape for the UI context sent to the backend"""

    active_dashboard: Optional[DashboardDisplayContext] = None
    active_insights: Optional[dict[str, InsightContextForMax]] = None
    global_info: Optional[GlobalInfo] = None
