"""Celery tasks for data_catalog.

Celery's autodiscovery imports this package, not the modules under it, so a task module that
nothing else imports never registers in a worker and its messages are discarded as unknown.
"""

from . import tasks

__all__ = ["tasks"]
