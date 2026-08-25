from collections.abc import Callable
from functools import wraps

from loginas.utils import is_impersonated_session
from rest_framework.request import Request
from rest_framework.response import Response


def disallow_if_impersonated(
    message: str = "Impersonated sessions cannot perform this action.",
    allowed_methods: list[str] | None = None,
):
    """
    Decorator that blocks impersonated sessions from executing the decorated action.

    Use this for endpoints where actions should only be performed by the actual user,
    and might pollute analytics data if done by an impersonated session.

    Args:
        message: Custom error message to return (default: "Impersonated sessions cannot perform this action.")
        allowed_methods: Optional list of HTTP methods that ARE allowed during impersonation (e.g., ["GET"]).
                        If None, blocks all methods. Methods not in this list will be blocked.

    Example:
        @disallow_if_impersonated(message="Impersonated sessions cannot set product intents.")
        def add_product_intent(self, request, *args, **kwargs):
            ...

        @disallow_if_impersonated(message="Cannot log views.", allowed_methods=["GET"])
        def log_view(self, request, *args, **kwargs):
            # GET requests are allowed during impersonation, all others are blocked
            ...
    """

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(self, request: Request, *args, **kwargs):
            if is_impersonated_session(request):
                # If allowed_methods specified, only allow those specific methods
                if allowed_methods is None or request.method not in allowed_methods:
                    return Response({"detail": message}, status=403)
            return f(self, request, *args, **kwargs)

        return wrapper

    return decorator
