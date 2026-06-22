"""Postgres source exceptions."""


class CDCHandledExternally(Exception):
    """Raised when a CDC streaming schema is encountered in source_for_pipeline.

    CDC streaming schemas are handled by CDCExtractionWorkflow, not by the
    regular ExternalDataJobWorkflow pipeline.
    """


class XminUnsupportedError(Exception):
    """Raised when an xmin sync targets a relation that can't support it.

    Deterministic (a server too old, or a partitioned parent), so the class name
    is listed in `PostgresSource.get_non_retryable_errors` to stop Temporal
    retrying into the same wall.
    """
