"""Facade re-export for the AEO Celery surface.

Core's central beat wiring (``posthog/tasks/scheduled.py``) registers the daily
citation-check run, the sentiment backlog pass and the stored-result refresh from here rather than reaching into the product's internals.
"""

from products.aeo.backend.tasks.tasks import (
    refresh_aeo_stored_results_task,
    run_aeo_citation_checks_task,
    score_aeo_sentiment_backlog_task,
)

__all__ = [
    "refresh_aeo_stored_results_task",
    "run_aeo_citation_checks_task",
    "score_aeo_sentiment_backlog_task",
]
