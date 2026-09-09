# Warehouse sources in experiment metrics

Experiment metrics store warehouse sources as `ExperimentDataWarehouseNode` values.
The metric editor converts these nodes to `ActionFilter` filters and converts edited filters back before saving.
Shared metrics use the same conversion.

| Editor filter field                | Experiment metric field   |
| ---------------------------------- | ------------------------- |
| `table_name`, falling back to `id` | `table_name`              |
| `timestamp_field`                  | `timestamp_field`         |
| `id_field`                         | `data_warehouse_join_key` |
| `aggregation_target_field`         | `events_join_key`         |

An existing warehouse filter can contain both the metric fields and their editor equivalents.
When converting it back, prefer `id_field` and `aggregation_target_field` because the editor updates those fields.
Use the metric join fields only as fallbacks when the editor fields are absent.
This preserves edited joins when selecting a different warehouse table.

Funnel conversion includes warehouse steps alongside events and actions, preserving their configured order.
The shared source converter handles mean metrics, ratio sources, and retention sources.

These mappings preserve explicitly selected joins; they do not infer existing warehouse joins automatically.
