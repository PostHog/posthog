from typing import Any, Optional, Union
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

    pass


class MaxNavigationContext(BaseModel):
    """Navigation context for Max"""

    path: str
    page_title: Optional[str] = None


class GlobalInfo(BaseModel):
    """General information that's always good to have, if available"""

    navigation: Optional[MaxNavigationContext] = None


class MaxContextShape(BaseModel):
    """The main shape for the UI context sent to the backend"""

    active_dashboard: Optional[DashboardDisplayContext] = None
    active_insights: Optional[dict[str, InsightContextForMax]] = None
    global_info: Optional[GlobalInfo] = None
