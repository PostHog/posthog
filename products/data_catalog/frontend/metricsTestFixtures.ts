import type { DataCatalogMetricApi } from './generated/api.schemas'

/** A catalog of `count` metrics, for tests that branch on the catalog size only. */
export function testMetrics(count: number): DataCatalogMetricApi[] {
    return Array.from({ length: count }, (_, index) => ({ name: `metric_${index}` }) as DataCatalogMetricApi)
}
