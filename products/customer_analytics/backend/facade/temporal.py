"""Temporal wiring re-exports — the only path core may use to register this
product's workflows, activities, and schedules."""

from products.customer_analytics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.customer_analytics.backend.temporal.calendar_sync import create_calendar_sync_coordinator_schedule

__all__ = ["ACTIVITIES", "WORKFLOWS", "create_calendar_sync_coordinator_schedule"]
