from typing import Any, Optional, Union
from pydantic import BaseModel, RootModel


class InsightContextForMax(BaseModel):
    """Context for a single insight, to be used by Max"""

    id: Union[str, int]
    name: Optional[str] = None
    description: Optional[str] = None
    query: dict[str, Any]  # The actual query node, e.g., TrendsQuery, HogQLQuery
    insight_type: Optional[str] = None  # Type of insight, e.g., NodeKind.TrendsQuery


class DashboardContextForMax(BaseModel):
    """Context for a dashboard being viewed, including its insights"""

    id: Union[str, int]
    name: Optional[str] = None
    description: Optional[str] = None
    insights: list[InsightContextForMax] = []


class MultiDashboardContextContainer(RootModel[dict[str, DashboardContextForMax]]):
    """Container for multiple dashboard contexts"""

    pass


class MultiInsightContextContainer(RootModel[dict[str, InsightContextForMax]]):
    """Container for multiple insight contexts"""

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

    dashboards: Optional[dict[str, DashboardContextForMax]] = None
    insights: Optional[dict[str, InsightContextForMax]] = None
    global_info: Optional[GlobalInfo] = None
