import { z } from 'zod'

import type { VizSpec } from '../../vizTypes'

export const metricOptionsSchema = z.strictObject({
    format: z.enum(['number', 'currency', 'percentage']).optional().describe('Format'),
})

export type MetricOptions = z.infer<typeof metricOptionsSchema>

export const metricSpec: VizSpec<MetricOptions> = {
    type: 'metric',
    label: 'Metric',
    // Eight rows fit the title, the number and the footer.
    size: { w: 6, h: 8, minW: 3, minH: 4 },
    optionsSchema: metricOptionsSchema,
}
