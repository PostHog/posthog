"""Celery tasks for the conversations product.

Celery keys tasks by the explicit name=, not by import path.
Queued messages and Beat entries resolve products.conversations.backend.tasks.<fn>.
"""

# Import modules so autodiscover registers every @shared_task. Do not re-export
# task symbols here: that double-binds them and breaks test patches.
from . import email, github, maintenance, slack, teams

__all__ = ["email", "github", "maintenance", "slack", "teams"]
