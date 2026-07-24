import { DataWarehouseMetrics } from 'products/data_warehouse/frontend/shared/components/metrics/DataWarehouseMetrics'

export function MetricsTab({ id }: { id: string }): JSX.Element {
    return <DataWarehouseMetrics logicKey={`dwh-source-metrics-${id}`} sourceId={id} />
}
