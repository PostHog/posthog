"""Postgres source exceptions."""


class CDCHandledExternally(Exception):
    """Raised when a CDC streaming schema is encountered in source_for_pipeline.

    CDC streaming schemas are handled by CDCExtractionWorkflow, not by the
    regular ExternalDataJobWorkflow pipeline.
    """
