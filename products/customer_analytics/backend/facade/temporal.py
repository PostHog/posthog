"""Temporal wiring re-exports — the only path core may use to register this
product's workflows, activities, and schedules."""

from products.customer_analytics.backend.facade.temporal_contracts import AccountPropertySyncInput
from products.customer_analytics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.customer_analytics.backend.temporal.account_property_sync import (
    ACCOUNT_PROPERTY_SYNC_ACTIVITIES,
    ACCOUNT_PROPERTY_SYNC_WORKFLOWS,
)
from products.customer_analytics.backend.temporal.account_track_rules import (
    create_account_track_rule_coordinator_schedule,
)
from products.customer_analytics.backend.temporal.calendar_sync import create_calendar_sync_coordinator_schedule

__all__ = [
    "ACCOUNT_PROPERTY_SYNC_ACTIVITIES",
    "ACCOUNT_PROPERTY_SYNC_WORKFLOWS",
    "ACTIVITIES",
    "WORKFLOWS",
    "AccountPropertySyncInput",
    "create_account_track_rule_coordinator_schedule",
    "create_calendar_sync_coordinator_schedule",
]
