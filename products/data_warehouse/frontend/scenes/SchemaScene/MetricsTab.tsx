import { DataWarehouseMetrics } from 'products/data_warehouse/frontend/shared/components/metrics/DataWarehouseMetrics'

export function MetricsTab({ sourceId, schemaId }: { sourceId: string; schemaId: string }): JSX.Element {
    return <DataWarehouseMetrics logicKey={`dwh-schema-metrics-${schemaId}`} sourceId={sourceId} schemaId={schemaId} />
}
