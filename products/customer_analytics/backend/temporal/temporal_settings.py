"""Temporal registration for the person-property sync workflow driven off warehouse data imports.

Runs on the VIDEO_EXPORT_TASK_QUEUE (same worker signals uses) and is wired in by
`start_temporal_worker`. Lives here (not warehouse_sources) because it depends on customer_analytics
internals; warehouse_sources only triggers it by workflow name via external_product_hooks.
"""

from products.customer_analytics.backend.temporal.person_property_sync_workflow import (
    SyncWarehousePersonPropertiesWorkflow,
    sync_warehouse_person_properties_activity,
)

PERSON_PROPERTY_SYNC_WORKFLOWS = [SyncWarehousePersonPropertiesWorkflow]
PERSON_PROPERTY_SYNC_ACTIVITIES = [sync_warehouse_person_properties_activity]
