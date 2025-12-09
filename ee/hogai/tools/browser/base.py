from typing import Any

from .session import BrowserSessionManager, HyperbrowserSession


class BrowserBaseToolMixin:
    """
    Base class for browser automation tools.

    Provides common functionality for accessing Hyperbrowser sessions
    and extracting conversation IDs from the config.
    """

    _conversation_id: str

    async def _get_session(self) -> HyperbrowserSession:
        """Get the Hyperbrowser session for this conversation."""
        return await BrowserSessionManager.get_or_create(self._conversation_id)

    async def _arun_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """Tool execution, which should return a tuple of (content, artifact)"""
        raise NotImplementedError
