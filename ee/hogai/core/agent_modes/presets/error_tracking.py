from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from products.error_tracking.backend.max_tools import ErrorTrackingExplainIssueTool, ErrorTrackingIssueFilteringTool

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class ErrorTrackingAgentToolkit(AgentToolkit):
    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [
            ErrorTrackingIssueFilteringTool,
            ErrorTrackingExplainIssueTool,
        ]


error_tracking_agent = AgentModeDefinition(
    mode=AgentMode.ERROR_TRACKING,
    mode_description="Specialized mode for error tracking and debugging. This mode allows you to filter error tracking issues and get explanations for errors with potential resolutions.",
    toolkit_class=ErrorTrackingAgentToolkit,
)
