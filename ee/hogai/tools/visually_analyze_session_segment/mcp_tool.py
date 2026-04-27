from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry
from ee.hogai.tools.replay.visually_analyze_session_segment import (
    VisuallyAnalyzeSessionSegmentArgs,
    visually_analyze_session_segment,
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
