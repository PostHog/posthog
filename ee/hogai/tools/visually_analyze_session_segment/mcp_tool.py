from pydantic import BaseModel, Field

from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry
from ee.hogai.tools.replay.visually_analyze_session_segment import visually_analyze_session_segment


class VisuallyAnalyzeSessionSegmentArgs(BaseModel):
    session_id: str = Field(description="The session recording ID to analyze.")
    start_timestamp: str = Field(description="Start timestamp within the session in hh:mm:ss format (e.g. '00:01:30').")
    end_timestamp: str = Field(description="End timestamp within the session in hh:mm:ss format (e.g. '00:03:00').")
    angle: str = Field(
        description="What to pay attention to when analyzing the video segment. "
        "For example: 'focus on user confusion around the checkout flow' or 'look for UI rendering issues'."
    )


@mcp_tool_registry.register(scopes=["session_recording:read"])
class VisuallyAnalyzeSessionSegmentMCPTool(MCPTool[VisuallyAnalyzeSessionSegmentArgs]):
    """
    Render a segment of a session recording as video and analyze it visually with Gemini.
    Uses the same rasterization pipeline as full session video summarization.
    """

    name = "visually_analyze_segment_of_session_recording"
    args_schema = VisuallyAnalyzeSessionSegmentArgs

    async def execute(self, args: VisuallyAnalyzeSessionSegmentArgs) -> str:
        return await visually_analyze_session_segment(
            team=self._team,
            user=self._user,
            session_id=args.session_id,
            start_timestamp=args.start_timestamp,
            end_timestamp=args.end_timestamp,
            angle=args.angle,
        )
