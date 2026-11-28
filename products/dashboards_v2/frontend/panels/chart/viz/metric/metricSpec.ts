import { z } from 'zod'

import { BREAKDOWN_FILTER_TYPE } from '../../../../filters/breakdown/breakdownFilterSpec'
import type { VizSpec } from '../../vizTypes'

export const metricOptionsSchema = z.strictObject({
    format: z.enum(['number', 'currency', 'percentage']).optional().describe('Format'),
})

export type MetricOptions = z.infer<typeof metricOptionsSchema>

export const metricSpec: VizSpec<MetricOptions> = {
    type: 'metric',
    label: 'Metric',
    // Eight rows fit the title, the number, its date and the sparkline. Any shorter and the sparkline goes.
    size: { w: 6, h: 8, minW: 4, minH: 8 },
    optionsSchema: metricOptionsSchema,
    ignoredFilterTypes: [BREAKDOWN_FILTER_TYPE],
}
