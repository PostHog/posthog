import re
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

from .base import BrowserBaseToolMixin

BROWSER_NAVIGATE_DESCRIPTION = """
Navigate the browser to a specific URL.

Use this tool to open a website or web page.
Then use the computer tool to interact with the page.
""".strip()


class BrowserNavigateToolArgs(BaseModel):
    url: str = Field(
        description="The URL to navigate to. Must be a valid HTTP or HTTPS URL.",
    )


class BrowserNavigateTool(MaxTool, BrowserBaseToolMixin):
    name: Literal["browser_navigate"] = "browser_navigate"
    description: str = BROWSER_NAVIGATE_DESCRIPTION
    args_schema: type[BaseModel] = BrowserNavigateToolArgs

    async def _arun_impl(self, url: str) -> tuple[str, Any]:
        # Validate URL
        validated_url = self._validate_url(url)

        session = await self._get_session()
        await session.navigate(validated_url)

        return (
            f"Navigated to {validated_url}. Use the computer tool with action='screenshot' to see the page.",
            {"url": validated_url},
        )

    def _validate_url(self, url: str) -> str:
        """
        Validate and sanitize the URL.

        Raises:
            MaxToolRetryableError: If the URL is invalid or blocked
        """
        # Add scheme if missing
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        try:
            parsed = urlparse(url)
        except Exception as e:
            raise MaxToolRetryableError(f"Invalid URL format: {url}") from e

        # Validate scheme
        if parsed.scheme not in ("http", "https"):
            raise MaxToolRetryableError(f"Invalid URL scheme: {parsed.scheme}. Only HTTP and HTTPS are allowed.")

        # Validate hostname exists
        if not parsed.hostname:
            raise MaxToolRetryableError(f"Invalid URL: missing hostname in {url}")

        # Block internal/private IPs
        hostname = parsed.hostname
        if self._is_private_host(hostname):
            raise MaxToolRetryableError(
                f"Access to internal/private addresses is not allowed: {hostname}. Only public URLs are permitted."
            )

        return url

    def _is_private_host(self, hostname: str) -> bool:
        """Check if hostname resolves to a private/internal IP."""
        # Block localhost and common internal hostnames
        blocked_hostnames = {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
            "host.docker.internal",
            "kubernetes.default",
        }

        if hostname.lower() in blocked_hostnames:
            return True

        # Block .local and .internal domains
        if hostname.endswith((".local", ".internal", ".localhost")):
            return True

        # Try to parse as IP address and check if private
        try:
            ip = ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
        except ValueError:
            # Not an IP address, hostname is fine
            pass

        # Block common internal IP patterns in hostnames
        internal_patterns = [
            r"^10\.",
            r"^172\.(1[6-9]|2[0-9]|3[0-1])\.",
            r"^192\.168\.",
            r"^169\.254\.",
        ]
        for pattern in internal_patterns:
            if re.match(pattern, hostname):
                return True

        return False
