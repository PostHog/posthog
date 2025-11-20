"""
Health check endpoint for WebSocket server.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def health_check(request):
    """
    Simple health check endpoint for the WebSocket server.

    Returns:
        JSON response with status OK and timestamp.
    """
    from django.utils import timezone

    return JsonResponse(
        {
            "status": "ok",
            "service": "websocket-server",
            "timestamp": timezone.now().isoformat(),
        }
    )
