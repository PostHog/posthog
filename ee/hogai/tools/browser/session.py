import asyncio
from typing import TYPE_CHECKING

from django.conf import settings

import structlog
from hyperbrowser.models import CreateSessionParams, ScreenConfig
from posthoganalytics import capture_exception

from ee.hogai.tool_errors import MaxToolFatalError

if TYPE_CHECKING:
    from hyperbrowser import AsyncHyperbrowser
    from hyperbrowser.models.session import SessionDetail

    from playwright.async_api import Browser, Page, Playwright

logger = structlog.get_logger(__name__)


class HyperbrowserSession:
    """
    Wrapper around a Hyperbrowser session that provides browser control via CDP.
    Maintains a persistent Playwright connection to the browser.
    """

    def __init__(self, session: "SessionDetail", client: "AsyncHyperbrowser"):
        self._session = session
        self._client = client
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    @property
    def session_id(self) -> str:
        return self._session.id

    @property
    def live_url(self) -> str | None:
        """Get the live view URL for debugging."""
        return self._session.live_url

    def get_cdp_url(self) -> str:
        """Get the CDP WebSocket URL for this session."""
        if not self._session.ws_endpoint:
            raise MaxToolFatalError("Session is not initialized or CDP URL is not available")
        return self._session.ws_endpoint

    async def _ensure_connected(self) -> "Page":
        """Ensure we have a connected browser and page, reconnecting if necessary."""
        from playwright.async_api import async_playwright

        # If we don't have a playwright instance, create one
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        # If we don't have a browser connection or it's closed, connect
        if self._browser is None or not self._browser.is_connected():
            cdp_url = self.get_cdp_url()
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                self._page = None  # Reset page when reconnecting
                logger.info("browser_connected", session_id=self.session_id, cdp_url=cdp_url)
            except Exception as e:
                logger.exception("browser_connection_failed", session_id=self.session_id, error=str(e))
                raise

        # Get or create a page
        if self._page is None or self._page.is_closed():
            contexts = self._browser.contexts
            if not contexts:
                context = await self._browser.new_context()
            else:
                context = contexts[0]

            pages = context.pages
            if not pages:
                self._page = await context.new_page()
            else:
                self._page = pages[0]

        return self._page

    async def screenshot(self) -> bytes:
        """Take a screenshot of the current page and return as PNG bytes."""
        page = await self._ensure_connected()
        screenshot_bytes = await page.screenshot(type="png")
        return screenshot_bytes

    async def navigate(self, url: str) -> None:
        """Navigate to a URL."""
        page = await self._ensure_connected()
        await page.goto(url, wait_until="domcontentloaded")

    async def click(self, x: int, y: int) -> None:
        """Click at the specified coordinates."""
        page = await self._ensure_connected()
        await page.mouse.click(x, y)

    async def double_click(self, x: int, y: int) -> None:
        """Double-click at the specified coordinates."""
        page = await self._ensure_connected()
        await page.mouse.dblclick(x, y)

    async def right_click(self, x: int, y: int) -> None:
        """Right-click at the specified coordinates."""
        page = await self._ensure_connected()
        await page.mouse.click(x, y, button="right")

    async def mouse_move(self, x: int, y: int) -> None:
        """Move the mouse to the specified coordinates."""
        page = await self._ensure_connected()
        await page.mouse.move(x, y)

    async def type_text(self, text: str) -> None:
        """Type text using the keyboard."""
        page = await self._ensure_connected()
        await page.keyboard.type(text)

    async def press_key(self, key: str) -> None:
        """Press a keyboard key."""
        page = await self._ensure_connected()
        await page.keyboard.press(key)

    async def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> None:
        """Scroll the page at the specified coordinates."""
        page = await self._ensure_connected()
        # Move mouse to position first, then scroll
        await page.mouse.move(x, y)
        await page.mouse.wheel(delta_x, delta_y)

    async def close(self) -> None:
        """Close this browser session."""
        try:
            # Close Playwright connection first
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.warning("playwright_browser_close_failed", session_id=self.session_id, error=str(e))
                self._browser = None
                self._page = None

            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning("playwright_stop_failed", session_id=self.session_id, error=str(e))
                self._playwright = None

            # Then stop the Hyperbrowser session
            await self._client.sessions.stop(self.session_id)
        except Exception as e:
            capture_exception(e)


class BrowserSessionManager:
    """
    Manages Hyperbrowser session state across tool calls within a conversation.

    Each conversation gets its own browser session, which is lazily initialized
    on first use and cleaned up when the conversation ends or times out.
    """

    _sessions: dict[str, HyperbrowserSession] = {}
    _locks: dict[str, asyncio.Lock] = {}

    # Default screen dimensions for computer use
    SCREEN_WIDTH = 1024
    SCREEN_HEIGHT = 768

    @classmethod
    def _get_lock(cls, conversation_id: str) -> asyncio.Lock:
        """Get or create a lock for a conversation to prevent race conditions."""
        if conversation_id not in cls._locks:
            cls._locks[conversation_id] = asyncio.Lock()
        return cls._locks[conversation_id]

    @classmethod
    async def get_or_create(cls, conversation_id: str) -> HyperbrowserSession:
        """
        Get an existing browser session or create a new one.

        Args:
            conversation_id: Unique identifier for the conversation

        Returns:
            HyperbrowserSession instance for this conversation

        Raises:
            MaxToolFatalError: If HYPERBROWSER_API_KEY is not configured
        """
        if not settings.HYPERBROWSER_API_KEY:
            raise MaxToolFatalError(
                "Browser automation is not available: HYPERBROWSER_API_KEY environment variable is not configured."
            )

        async with cls._get_lock(conversation_id):
            if conversation_id not in cls._sessions:
                try:
                    from hyperbrowser import AsyncHyperbrowser

                    client = AsyncHyperbrowser(api_key=settings.HYPERBROWSER_API_KEY)

                    # Create a new browser session with specified screen size
                    session = await client.sessions.create(
                        CreateSessionParams(
                            screen=ScreenConfig(
                                width=cls.SCREEN_WIDTH,
                                height=cls.SCREEN_HEIGHT,
                            )
                        ),
                    )

                    wrapped_session = HyperbrowserSession(session, client)
                    cls._sessions[conversation_id] = wrapped_session

                    logger.info(
                        "hyperbrowser_session_created",
                        conversation_id=conversation_id,
                        session_id=session.id,
                        live_url=session.live_url,
                        ws_endpoint=session.ws_endpoint,
                    )
                except ImportError as e:
                    raise MaxToolFatalError(
                        "Browser automation is not available: hyperbrowser package is not installed. "
                        "Install it with: pip install hyperbrowser"
                    ) from e
                except Exception as e:
                    logger.exception(
                        "hyperbrowser_session_creation_failed",
                        conversation_id=conversation_id,
                        error=str(e),
                    )
                    raise MaxToolFatalError(f"Failed to start browser session: {e}") from e

            return cls._sessions[conversation_id]

    @classmethod
    async def get_current_session(cls, conversation_id: str) -> HyperbrowserSession:
        """
        Get the current session from the browser session manager.
        Unlike get_or_create, this requires a session to already exist.

        Args:
            conversation_id: Unique identifier for the conversation

        Returns:
            Current HyperbrowserSession object

        Raises:
            MaxToolRetryableError: If no browser session exists
        """
        from ee.hogai.tool_errors import MaxToolRetryableError

        if conversation_id not in cls._sessions:
            raise MaxToolRetryableError(
                "No browser session is active. Use the browser_navigate tool first to open a webpage."
            )
        return cls._sessions[conversation_id]

    @classmethod
    async def close(cls, conversation_id: str) -> None:
        """
        Close and clean up a browser session.

        Args:
            conversation_id: Unique identifier for the conversation
        """
        async with cls._get_lock(conversation_id):
            if conversation_id in cls._sessions:
                try:
                    await cls._sessions[conversation_id].close()
                except Exception as e:
                    logger.warning(
                        "hyperbrowser_session_close_failed",
                        conversation_id=conversation_id,
                        error=str(e),
                    )
                finally:
                    del cls._sessions[conversation_id]

            # Clean up the lock if no longer needed
            if conversation_id in cls._locks:
                del cls._locks[conversation_id]

    @classmethod
    async def close_all(cls) -> None:
        """Close all active browser sessions. Useful for cleanup during shutdown."""
        conversation_ids = list(cls._sessions.keys())
        for conversation_id in conversation_ids:
            await cls.close(conversation_id)

    @classmethod
    def get_active_session_count(cls) -> int:
        """Get the number of active browser sessions."""
        return len(cls._sessions)
