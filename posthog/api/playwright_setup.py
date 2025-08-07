"""
Test setup API endpoint for Playwright tests.
Only available in TEST, DEBUG, CI, or E2E_TESTING modes for security.
"""

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from pydantic import BaseModel

from posthog.test.playwright_setup_functions import PLAYWRIGHT_SETUP_FUNCTIONS


@api_view(["POST"])
@permission_classes([AllowAny])
def setup_test(request: Request, test_name: str) -> Response:
    """
    Endpoint to setup test data for Playwright tests.
    Only accessible in TEST, DEBUG, CI, or E2E_TESTING modes for security.

    Args:
        request: Django request object
        test_name: Name of the test setup function to run

    Returns:
        JSON response with setup result
    """
    # Only allow in TEST, DEBUG, CI, or E2E_TESTING modes
    is_test_mode = getattr(settings, "TEST", False)
    is_debug_mode = getattr(settings, "DEBUG", False)
    is_ci_mode = getattr(settings, "CI", False)
    is_e2e_testing = getattr(settings, "E2E_TESTING", False)

    if not (is_test_mode or is_debug_mode or is_ci_mode or is_e2e_testing):
        return Response(
            {"error": "Test setup endpoint only available in TEST, DEBUG, CI, or E2E_TESTING modes"},
            status=status.HTTP_403_FORBIDDEN,
        )

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

        # Get the function's parameter type annotation to create the right data model
        import inspect
        from typing import get_type_hints

        request_data = request.data if hasattr(request, "data") else {}

        # Get function signature and parameter types
        sig = inspect.signature(setup_function)
        type_hints = get_type_hints(setup_function)

        # Get the first parameter's type (should be the data model)
        param_names = list(sig.parameters.keys())
        if param_names:
            first_param = param_names[0]
            if first_param in type_hints:
                data_model_class = type_hints[first_param]
                # Create instance of the expected data model
                setup_data = data_model_class(**request_data)
            else:
                # Fallback to raw data if no type annotation
                setup_data = request_data
        else:
            setup_data = request_data

        # Run the setup function with proper data type - returns a BaseModel
        result: BaseModel = setup_function(setup_data)

        # Convert Pydantic BaseModel to dict for JSON serialization
        result_dict = result.model_dump()

        return Response({"success": True, "test_name": test_name, "result": result_dict})

    except Exception as e:
        return Response(
            {"error": f"Failed to run playwright setup '{test_name}': {str(e)}", "test_name": test_name},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
