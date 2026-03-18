from typing import Literal


class MaxToolError(Exception):
    """
    Base exception for MaxTool failures. All errors produce tool messages visible to LLM but not end users.

    Error Handling Strategy:
    - MaxToolFatalError: Show-stoppers that cannot be recovered from (e.g., permissions, missing config)
    - MaxToolTransientError: Intermittent issues that can be retried without changes (e.g., rate limits, timeouts)
    - MaxToolRetryableError: Solvable issues that can be fixed with adjusted inputs (e.g., invalid parameters)
    - Generic Exception: Unknown failures, treated as fatal (safety net)

    When raising these exceptions, provide actionable context about:
    - What went wrong
    - Why it went wrong (for retryable errors)
    - What can be done about it (for retryable errors)
    """

    def __init__(self, message: str):
        """
        Args:
            message: Detailed, actionable error message that helps the LLM understand what went wrong
        """
        super().__init__(message)

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        """
        Returns the retry strategy for this error:
        - "never": Do not retry (fatal errors)
        - "once": Retry once without changes (transient errors)
        - "adjusted": Retry with adjusted inputs (solvable errors)
        """
        return "never"

    @property
    def retry_hint(self) -> str:
        """
        Returns the retry hint message to append to error messages for the LLM.
        """
        retry_hints = {
            "never": "",
            "once": " You may retry this operation once without changes.",
            "adjusted": " You may retry with adjusted inputs.",
        }
        return retry_hints[self.retry_strategy]

    def to_summary(self, max_length: int = 500) -> str:
        """
        Create a truncated summary for context management.

        Args:
            max_length: Maximum length of the error message before truncation

        Returns:
            Formatted string with exception class name and truncated message
        """
        exception_name = self.__class__.__name__
        exception_msg = str(self).strip()
        if len(exception_msg) > max_length:
            exception_msg = exception_msg[:max_length] + "…"
        return f"{exception_name}: {exception_msg}"


class MaxToolFatalError(MaxToolError):
    """
    Fatal error that cannot be recovered from. Do not retry.
    """

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "never"


class MaxToolTransientError(MaxToolError):
    """
    Transient error due to temporary service issues. Can be retried once without changes.
    """

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "once"


class MaxToolRetryableError(MaxToolError):
    """
    Solvable error that can be fixed with adjusted inputs. Can be retried with corrections.
    """

    @property
    def retry_strategy(self) -> Literal["never", "once", "adjusted"]:
        return "adjusted"


class MaxToolAccessDeniedError(MaxToolFatalError):
    """
    Access denied error when user doesn't have permission to use a tool or access a resource.
    This is a fatal error - the user needs to contact their admin to get access.
    """

    def __init__(
        self,
        resource: str,
        required_level: str,
        action: str = "access",
    ):
        self.resource = resource
        self.required_level = required_level
        self.action = action

        message = f"The user does not have {required_level} access to {action} {resource}s. Suggest the user to contact their project admin to request access."
        super().__init__(message)
