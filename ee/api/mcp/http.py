from mcp_server.views import MCPServerStreamableHttpView
from posthog.auth import PersonalAPIKeyAuthentication
from rest_framework.permissions import IsAuthenticated

from .base import mcp

mcp_view = MCPServerStreamableHttpView.as_view(
    mcp_server=mcp, authentication_classes=[PersonalAPIKeyAuthentication], permission_classes=[IsAuthenticated]
)
