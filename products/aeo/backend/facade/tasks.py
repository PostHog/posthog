"""Facade re-export for the AEO Celery surface.

Core's central beat wiring (``posthog/tasks/scheduled.py``) registers the daily
citation-check run from here rather than reaching into the product's internals.
"""

from products.aeo.backend.tasks.tasks import run_aeo_citation_checks_task

__all__ = ["run_aeo_citation_checks_task"]
