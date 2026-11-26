import type { BillingTimeSeriesPointApi } from 'products/billing/frontend/generated/api.schemas'

import type { BillingSpendResponse } from './billingSpendLogic'
import type { BillingUsageResponse } from './billingUsageLogic'

/** The API describes a series with every field optional, and the charts draw only complete ones. The pages' breakdown
 * enums hold the same strings as the generated one. */
export function chartSeries<Response extends BillingUsageResponse | BillingSpendResponse>(
    points: BillingTimeSeriesPointApi[]
): Response['results'] {
    return points.map((point) => ({
        id: point.id ?? 0,
        label: point.label ?? '',
        data: point.data ?? [],
        dates: point.dates ?? [],
        breakdown_type: point.breakdown_type ?? null,
        breakdown_value: (point.breakdown_value as string | string[] | null | undefined) ?? null,
    })) as Response['results']
}
