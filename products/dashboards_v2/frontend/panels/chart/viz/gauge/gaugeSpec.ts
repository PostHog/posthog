import { z } from 'zod'

import type { VizSpec } from '../../vizTypes'

export const gaugeOptionsSchema = z.strictObject({
    min: z.number().optional().describe('Minimum'),
    max: z.number().optional().describe('Maximum'),
})

export type GaugeOptions = z.infer<typeof gaugeOptionsSchema>

export const gaugeSpec: VizSpec<GaugeOptions> = {
    type: 'gauge',
    label: 'Gauge',
    size: { w: 6, h: 10, minW: 3, minH: 6 },
    optionsSchema: gaugeOptionsSchema,
}
