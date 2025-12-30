class ApprovalException(Exception):
    """Base exception for approval-related errors"""

    pass


class PreconditionFailed(ApprovalException):
    """Raised when preconditions for applying a change no longer hold"""

    pass


class ApplyFailed(ApprovalException):
    """Raised when applying an approved change fails"""

    pass


class InvalidIntent(ApprovalException):
    """Raised when intent data is invalid"""

    pass


class PolicyEvaluationError(ApprovalException):
    """Raised when policy evaluation fails"""

    pass


class ApprovalRequired(ApprovalException):
    """
    Raised when an action requires approval.

    This exception is raised from serializer methods when approval is required,
    allowing the ViewSet to catch it and return the appropriate 409 response.
    """

    def __init__(self, change_request, message: str, required_approvers: dict, error_code: str = "approval_required"):
        self.change_request = change_request
        self.message = message
        self.required_approvers = required_approvers
        self.error_code = error_code
        super().__init__(message)


class ChangeRequestError(ApprovalException):
    """Base exception for change request service operations."""

    pass


class InvalidStateError(ChangeRequestError):
    """Raised when operation is invalid for the current change request state."""

    pass


class AlreadyVotedError(ChangeRequestError):
    """Raised when user has already voted on a change request."""

    pass


class ReasonRequiredError(ChangeRequestError):
    """Raised when a reason is required but not provided."""

    pass
