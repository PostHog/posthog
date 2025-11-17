"""Test setup API endpoint for Playwright tests."""

from django.conf import settings
from django.http import Http404

from pydantic import BaseModel
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.test.playwright_setup_functions import PLAYWRIGHT_SETUP_FUNCTIONS


@api_view(["POST"])
@permission_classes([AllowAny])
def setup_test(request: Request, test_name: str) -> Response:
    """Setup test data for Playwright tests. Only accessible in test/debug/CI modes."""
    test_modes = (
        getattr(settings, "TEST", False),
        getattr(settings, "DEBUG", False),
        getattr(settings, "CI", False),
        getattr(settings, "E2E_TESTING", False),
    )

    if not any(test_modes):
        raise Http404()

    if test_name not in PLAYWRIGHT_SETUP_FUNCTIONS:
        available_tests = {name: config.description for name, config in PLAYWRIGHT_SETUP_FUNCTIONS.items()}
        return Response(
            {"error": f"Playwright setup function '{test_name}' not found", "available_tests": available_tests},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        setup_config = PLAYWRIGHT_SETUP_FUNCTIONS[test_name]
        request_data = request.data if hasattr(request, "data") else {}
        setup_input = setup_config.input_model.model_validate(request_data)
        result: BaseModel = setup_config.function(setup_input)

        return Response({"success": True, "test_name": test_name, "result": result.model_dump()})

    except Exception as e:
        return Response(
            {"error": f"Failed to run playwright setup '{test_name}': {str(e)}", "test_name": test_name},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
