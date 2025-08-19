"""
Centralized error handling for experiments to ensure users see friendly error messages
while technical details are logged for engineers.
"""

import functools
from typing import Any, Optional, TypeVar, Union
from collections.abc import Callable
import structlog
from rest_framework.exceptions import ValidationError
from posthog.exceptions_capture import capture_exception
from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError
from posthog.errors import ExposedCHQueryError
from products.experiments.stats.shared.statistics import StatisticError

logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# User-friendly error messages for technical errors
ERROR_MESSAGES: dict[str, str] = {
    # Statistical errors
    "Sample size must be positive": "Not enough data to calculate results. Please wait for more participants to join the experiment.",
    "sum_squares must be >= sum^2": "Invalid metric data detected. Please check your metric configuration and try again.",
    "sum_squares incompatible with sum and n": "Unable to calculate statistics due to data inconsistency. Please refresh and try again.",
    "No control variant found": "No control group data available. Please ensure your experiment has a control variant.",
    "Multiple control variants found": "Multiple control groups detected. Please check your experiment configuration.",
    # Validation errors
    "NOT_ENOUGH_EXPOSURES": "Not enough participants yet. Experiments need at least 50 participants per variant.",
    "NOT_ENOUGH_METRIC_DATA": "Not enough conversion data. Please wait for more events to be tracked.",
    "BASELINE_MEAN_IS_ZERO": "The control group has no metric data. Please check your metric configuration.",
    # HogQL errors
    "Unable to execute experiment analysis": "Unable to calculate experiment results. Please check your metric configuration and try again.",
    "Query timeout": "The analysis is taking too long. Try refreshing the page or simplifying your metrics.",
    # Default fallback
    "_DEFAULT": "Unable to calculate experiment results. Please try again or contact support if the issue persists.",
}


def get_user_friendly_message(error: Exception) -> str:
    """Convert technical error messages to user-friendly ones."""
    error_str = str(error)

    # Check for exact matches first
    if error_str in ERROR_MESSAGES:
        return ERROR_MESSAGES[error_str]

    # Check for partial matches
    for key, message in ERROR_MESSAGES.items():
        if key in error_str:
            return message

    # Special handling for specific error types
    if isinstance(error, StatisticError):
        return "Unable to calculate statistics. Please ensure your experiment has sufficient data."
    elif isinstance(error, InternalHogQLError | ExposedHogQLError):
        return "Unable to process your query. Please check your metric configuration."
    elif isinstance(error, ExposedCHQueryError):
        return "Unable to retrieve experiment data. Please try again."

    # Default message
    return ERROR_MESSAGES["_DEFAULT"]


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
            experiment_id = getattr(self, "experiment_id", None) or getattr(self, "experiment", {}).get("id", "unknown")
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


def handle_experiment_error(
    error: Exception,
    experiment_id: Optional[Union[str, int]] = None,
    metric_type: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """
    Utility function to handle experiment errors consistently.
    Logs the error and raises a user-friendly ValidationError.
    """
    # Log the technical error
    logger.error(
        "Experiment error",
        experiment_id=experiment_id,
        metric_type=metric_type,
        error_type=type(error).__name__,
        error_message=str(error),
        context=context,
        exc_info=True,
    )

    # Capture for error tracking
    capture_exception(
        error, additional_properties={"experiment_id": experiment_id, "metric_type": metric_type, **(context or {})}
    )

    # Raise user-friendly error
    user_message = get_user_friendly_message(error)
    raise ValidationError(user_message)
