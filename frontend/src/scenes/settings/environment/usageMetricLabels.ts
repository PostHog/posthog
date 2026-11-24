import type { GroupUsageMetricApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { UsageMetricFiltersDataWarehouse, UsageMetricFormData, getMetricSource } from './usageMetricsConfigLogic'

export function usageMetricDisplayLabel(metric: GroupUsageMetricApi): string {
    return metric.display === 'sparkline' ? 'Sparkline' : 'Number'
}

export function usageMetricSourceLabel(metric: GroupUsageMetricApi): string {
    const source = getMetricSource(metric.filters as UsageMetricFormData['filters'])
    if (source === 'data_warehouse') {
        const dwFilters = metric.filters as UsageMetricFiltersDataWarehouse
        return `Warehouse · ${dwFilters?.table_name ?? '(unknown table)'}`
    }
    return 'Events'
}

export function usageMetricCalculationLabel(metric: GroupUsageMetricApi): string {
    if (metric.math === 'sum') {
        return `Sum of ${metric.math_property ?? '(unknown)'}`
    }
    return 'Count'
}
