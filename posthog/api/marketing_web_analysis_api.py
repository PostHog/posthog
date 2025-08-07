"""
Simple Marketing Web Analysis API.
"""

from collections.abc import Generator

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.permissions import AllowAny

from ee.hogai.utils.asgi import SyncIterableToAsync
from posthog.marketing_graph_execution.core import MarketingGraphExecutor


class MarketingWebAnalysisViewSet(viewsets.ViewSet):
    """Open Marketing Web Analysis API - no authentication required."""

    permission_classes = [AllowAny]

    def _stream_response(self, data: dict) -> Generator[str, None, None]:
        """Generate streaming response."""
        executor = MarketingGraphExecutor()

        # Convert QueryDict to regular dict with single values
        processed_data = {}
        for key, value in data.items():
            # QueryDict.items() returns (key, value) where value is a list
            # We want the first (and usually only) value
            processed_data[key] = value if isinstance(value, str) else value[0] if value else ""

        yield from executor.execute_with_streaming(processed_data)

    @action(detail=False, methods=["GET"])
    def website_analysis(self, request: Request) -> StreamingHttpResponse:
        """Analyze website with streaming response."""
        data = request.query_params

        response = self._stream_response(data)

        stream = StreamingHttpResponse(
            SyncIterableToAsync(response) if settings.SERVER_GATEWAY_INTERFACE == "ASGI" else response,
            content_type="text/event-stream",
        )
        return stream
