"""Errors raised while validating or compiling a check.

Plain exceptions, not DRF ``APIException``s: these are raised from Temporal activities as well as
from serializers, and the presentation layer is responsible for mapping them to a status code.
"""


class CheckConfigError(ValueError):
    """The check's config, column, or custom query is unusable for its type."""


class SubjectUnresolvableError(ValueError):
    """The subject a check targets no longer resolves in its owning product."""
