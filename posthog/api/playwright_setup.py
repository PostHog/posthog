"""
Test setup API endpoint for Playwright tests.
Only available in TEST mode for security.
"""

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.test.playwright_setup_functions import PLAYWRIGHT_SETUP_FUNCTIONS


@api_view(["POST"])
@permission_classes([AllowAny])
def setup_test(request: Request, test_name: str) -> Response:
    """
    Endpoint to setup test data for Playwright tests.
    Only accessible in TEST mode for security.

    Args:
        request: Django request object
        test_name: Name of the test setup function to run

    Returns:
        JSON response with setup result
    """
    # Only allow in TEST mode
    if not getattr(settings, "TEST", False):
        return Response({"error": "Test setup endpoint only available in TEST mode"}, status=status.HTTP_403_FORBIDDEN)

    # Check if test setup function exists
    if test_name not in PLAYWRIGHT_SETUP_FUNCTIONS:
        available_tests = list(PLAYWRIGHT_SETUP_FUNCTIONS.keys())
        return Response(
            {"error": f"Playwright setup function '{test_name}' not found", "available_tests": available_tests},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        # Get the setup function
        setup_function = PLAYWRIGHT_SETUP_FUNCTIONS[test_name]

        # Run the setup function with request data
        result = setup_function(request.data if hasattr(request, "data") else {})

        return Response({"success": True, "test_name": test_name, "result": result})

    except Exception as e:
        return Response(
            {"error": f"Failed to run playwright setup '{test_name}': {str(e)}", "test_name": test_name},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
