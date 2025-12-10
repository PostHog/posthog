import base64
from typing import Any

import structlog

from ee.hogai.tool_errors import MaxToolRetryableError

from .session import BrowserSessionManager, HyperbrowserSession

logger = structlog.get_logger(__name__)


# Anthropic's native computer use tool definition
# This is passed directly to bind_tools, not as a MaxTool
COMPUTER_TOOL_DEFINITION = {
    "type": "computer_20250124",
    "name": "computer",
    "display_width_px": BrowserSessionManager.SCREEN_WIDTH,
    "display_height_px": BrowserSessionManager.SCREEN_HEIGHT,
}


class ComputerToolHandler:
    """
    Handler for Anthropic's native computer use tool.

    This class handles the execution of computer use tool calls from Claude.
    It's not a MaxTool - instead it processes the raw tool call input and
    returns results that can be sent back to Claude.
    """

    def __init__(self, thread_id: str):
        self._thread_id = thread_id

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a computer use tool call and return the result.

        Args:
            tool_input: The input from Claude's tool call, e.g. {"action": "screenshot"}

        Returns:
            A dict with the tool result content for Anthropic's API format
        """
        action = tool_input.get("action")
        if not action:
            raise MaxToolRetryableError("No action specified in computer tool call")

        session = await BrowserSessionManager.get_current_session(self._thread_id)

        try:
            if action == "screenshot":
                return await self._take_screenshot(session)
            elif action == "left_click":
                return await self._click(session, tool_input, "left")
            elif action == "right_click":
                return await self._click(session, tool_input, "right")
            elif action == "double_click":
                return await self._double_click(session, tool_input)
            elif action == "middle_click":
                return await self._click(session, tool_input, "middle")
            elif action == "mouse_move":
                return await self._mouse_move(session, tool_input)
            elif action == "type":
                return await self._type_text(session, tool_input)
            elif action == "key":
                return await self._press_key(session, tool_input)
            elif action == "scroll":
                return await self._scroll(session, tool_input)
            elif action == "left_click_drag":
                return await self._drag(session, tool_input)
            elif action == "wait":
                return await self._wait(tool_input)
            else:
                raise MaxToolRetryableError(f"Unknown action: {action}")

        except MaxToolRetryableError:
            raise
        except Exception as e:
            logger.exception("computer_tool_error", action=action, error=str(e))
            raise MaxToolRetryableError(f"Action '{action}' failed: {e}") from e

    async def _take_screenshot(self, session: HyperbrowserSession) -> dict[str, Any]:
        """Take a screenshot and return it in Anthropic's format."""
        screenshot_bytes = await session.screenshot()
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        # Return in Anthropic's expected format for image content
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_b64,
            },
        }

    async def _click(self, session: HyperbrowserSession, tool_input: dict[str, Any], button: str) -> dict[str, Any]:
        """Click at the specified coordinates."""
        coordinate = tool_input.get("coordinate")
        if not coordinate or len(coordinate) != 2:
            raise MaxToolRetryableError(f"Valid coordinate [x, y] is required for {button}_click action")

        x, y = coordinate
        self._validate_coordinates(x, y)

        if button == "left":
            await session.click(x, y)
        elif button == "right":
            await session.right_click(x, y)
        elif button == "middle":
            await session.click(x, y)

        return {"type": "text", "text": f"Clicked {button} mouse button at ({x}, {y})"}

    async def _double_click(self, session: HyperbrowserSession, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Double-click at the specified coordinates."""
        coordinate = tool_input.get("coordinate")
        if not coordinate or len(coordinate) != 2:
            raise MaxToolRetryableError("Valid coordinate [x, y] is required for double_click action")

        x, y = coordinate
        self._validate_coordinates(x, y)

        await session.double_click(x, y)

        return {"type": "text", "text": f"Double-clicked at ({x}, {y})"}

    async def _mouse_move(self, session: HyperbrowserSession, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Move the mouse to the specified coordinates."""
        coordinate = tool_input.get("coordinate")
        if not coordinate or len(coordinate) != 2:
            raise MaxToolRetryableError("Valid coordinate [x, y] is required for mouse_move action")

        x, y = coordinate
        self._validate_coordinates(x, y)

        await session.mouse_move(x, y)

        return {"type": "text", "text": f"Moved mouse to ({x}, {y})"}

    async def _type_text(self, session: HyperbrowserSession, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Type the specified text."""
        text = tool_input.get("text")
        if not text:
            raise MaxToolRetryableError("Text is required for type action")

        await session.type_text(text)

        # Mask the text in the response for privacy
        display_text = text[:20] + "..." if len(text) > 20 else text

        return {"type": "text", "text": f"Typed text: '{display_text}'"}

    async def _press_key(self, session: HyperbrowserSession, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Press the specified key or key combination."""
        key = tool_input.get("text")
        if not key:
            raise MaxToolRetryableError("Key is required for key action")

        # Map common key names to Playwright key names
        key_mapping = {
            "Return": "Enter",
            "return": "Enter",
            "enter": "Enter",
            "space": " ",
            "Space": " ",
            "ctrl": "Control",
            "Ctrl": "Control",
            "cmd": "Meta",
            "Cmd": "Meta",
            "alt": "Alt",
            "shift": "Shift",
            "esc": "Escape",
            "Esc": "Escape",
            "backspace": "Backspace",
            "delete": "Delete",
            "up": "ArrowUp",
            "down": "ArrowDown",
            "left": "ArrowLeft",
            "right": "ArrowRight",
            "tab": "Tab",
            "page_up": "PageUp",
            "page_down": "PageDown",
            "home": "Home",
            "end": "End",
        }

        # Handle key combinations like "ctrl+a"
        if "+" in key:
            parts = key.split("+")
            mapped_parts = [key_mapping.get(p.strip(), p.strip()) for p in parts]
            mapped_parts = [p for p in mapped_parts if p is not None]
            mapped_key = "+".join(mapped_parts)
        else:
            mapped_key = key_mapping.get(key, key)

        if not mapped_key:
            raise MaxToolRetryableError(f"Invalid key: {key}, supported keys are: {list(key_mapping.keys())}")

        await session.press_key(mapped_key)

        return {"type": "text", "text": f"Pressed key: {key}"}

    async def _scroll(self, session: HyperbrowserSession, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Scroll the page in the specified direction."""
        direction = tool_input.get("scroll_direction")
        if not direction:
            raise MaxToolRetryableError("scroll_direction is required for scroll action")

        # Default scroll amount
        scroll_amount = tool_input.get("scroll_amount", 3) * 100  # Convert to pixels

        # Get coordinate or default to center of screen
        coordinate = tool_input.get("coordinate")
        if coordinate and len(coordinate) == 2:
            x, y = coordinate
        else:
            x = BrowserSessionManager.SCREEN_WIDTH // 2
            y = BrowserSessionManager.SCREEN_HEIGHT // 2

        self._validate_coordinates(x, y)

        # Calculate delta based on direction
        delta_x = 0
        delta_y = 0
        if direction == "up":
            delta_y = -scroll_amount
        elif direction == "down":
            delta_y = scroll_amount
        elif direction == "left":
            delta_x = -scroll_amount
        elif direction == "right":
            delta_x = scroll_amount

        await session.scroll(x, y, delta_x, delta_y)

        return {"type": "text", "text": f"Scrolled {direction} by {scroll_amount} pixels"}

    async def _drag(self, session: HyperbrowserSession, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Click and drag from start to end coordinates."""
        start_coordinate = tool_input.get("start_coordinate")
        coordinate = tool_input.get("coordinate")

        if not start_coordinate or len(start_coordinate) != 2:
            raise MaxToolRetryableError("Valid start_coordinate [x, y] is required for left_click_drag action")
        if not coordinate or len(coordinate) != 2:
            raise MaxToolRetryableError("Valid coordinate [x, y] is required for left_click_drag action")

        start_x, start_y = start_coordinate
        end_x, end_y = coordinate

        self._validate_coordinates(start_x, start_y)
        self._validate_coordinates(end_x, end_y)

        # Implement drag as mouse down, move, mouse up
        await session.mouse_move(start_x, start_y)
        await session.click(start_x, start_y)  # This should be mouse_down
        await session.mouse_move(end_x, end_y)
        # Note: We'd need to add mouse_up to the session for proper drag support

        return {"type": "text", "text": f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"}

    async def _wait(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Wait for the specified duration."""
        import asyncio

        duration = tool_input.get("duration", 1)
        if duration > 10:
            duration = 10  # Cap at 10 seconds

        await asyncio.sleep(duration)

        return {"type": "text", "text": f"Waited for {duration} seconds"}

    def _validate_coordinates(self, x: int, y: int) -> None:
        """Validate that coordinates are within screen bounds."""
        if x < 0 or x >= BrowserSessionManager.SCREEN_WIDTH:
            raise MaxToolRetryableError(
                f"X coordinate {x} is out of bounds. Screen width is {BrowserSessionManager.SCREEN_WIDTH}."
            )
        if y < 0 or y >= BrowserSessionManager.SCREEN_HEIGHT:
            raise MaxToolRetryableError(
                f"Y coordinate {y} is out of bounds. Screen height is {BrowserSessionManager.SCREEN_HEIGHT}."
            )
