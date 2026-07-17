"""
Celery-task and schedule wiring for data_modeling.

Re-exports the beat-scheduled cleanup task (name-pinned) and the schedule-spec builder
core's scheduler registers.
"""

from products.data_modeling.backend.schedule import build_schedule_spec
from products.data_modeling.backend.tasks.cleanup_test_saved_queries import cleanup_expired_test_saved_queries

__all__ = ["build_schedule_spec", "cleanup_expired_test_saved_queries"]
