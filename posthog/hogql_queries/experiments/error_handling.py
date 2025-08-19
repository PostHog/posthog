"""
Centralized error handling for experiments to ensure users see friendly error messages
while technical details are logged for engineers.
"""

import functools
from typing import Any, TypeVar
from collections.abc import Callable
import structlog
from rest_framework.exceptions import ValidationError
from posthog.exceptions_capture import capture_exception
from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError
from posthog.errors import ExposedCHQueryError
from products.experiments.stats.shared.statistics import StatisticError

logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# User-friendly error messages for different error types
ERROR_TYPE_MESSAGES: dict[type, str] = {
    # Statistical calculation errors
    StatisticError: "Unable to calculate experiment statistics. Please ensure your experiment has sufficient data and try again.",
    # HogQL/Query errors
    InternalHogQLError: "Unable to process your experiment query. Please check your metric configuration and try again.",
    ExposedCHQueryError: "Unable to retrieve experiment data. Please try refreshing the page.",
    # Python built-in errors that can occur during calculation
    ValueError: "Invalid experiment configuration detected. Please check your experiment setup.",
    ZeroDivisionError: "Unable to calculate results due to insufficient data. Please wait for more experiment data.",
    # Default fallback
    Exception: "Unable to calculate experiment results. Please try again or contact support if the issue persists.",
}


def get_user_friendly_message(error: Exception) -> str:
    """Convert technical error messages to user-friendly ones based on error type."""
    error_type = type(error)

    # Look for exact type match first
    if error_type in ERROR_TYPE_MESSAGES:
        return ERROR_TYPE_MESSAGES[error_type]

    # Check if error is an instance of any of the registered types
    for registered_type, message in ERROR_TYPE_MESSAGES.items():
        if isinstance(error, registered_type):
            return message

    # Default fallback
    return ERROR_TYPE_MESSAGES[Exception]


def experiment_error_handler(method: F) -> F:
    """
    Decorator that catches technical errors, logs them for engineers,
    and raises user-friendly errors for the frontend.
    """

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (ValidationError, ExposedHogQLError):
            # ValidationErrors and ExposedHogQLErrors are already user-facing, let them through
            raise
        except Exception as e:
            # Get context for logging
            self = args[0] if args else None
            experiment_id = "unknown"
            if hasattr(self, "experiment_id"):
                experiment_id = self.experiment_id
            elif hasattr(self, "experiment") and hasattr(self.experiment, "id"):
                experiment_id = self.experiment.id

            metric_type = None
            if hasattr(self, "metric"):
                metric_type = getattr(self.metric, "__class__", type(self.metric)).__name__

            # Log the technical error for engineers
            logger.error(
                "Experiment calculation error",
                experiment_id=experiment_id,
                metric_type=metric_type,
                error_type=type(e).__name__,
                error_message=str(e),
                error_detail=getattr(e, "detail", None),
                exc_info=True,
            )

            # Capture exception for error tracking
            capture_exception(
                e,
                additional_properties={
                    "experiment_id": experiment_id,
                    "metric_type": metric_type,
                    "method": method.__name__,
                },
            )

            # Raise user-friendly error
            user_message = get_user_friendly_message(e)
            raise ValidationError(user_message)

    return wrapper
