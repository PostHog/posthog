import type { DataCatalogMetricApi } from './generated/api.schemas'

export function testMetrics(count: number): DataCatalogMetricApi[] {
    return Array.from({ length: count }, (_, index) => ({ name: `metric_${index}` }) as DataCatalogMetricApi)
}
