import { z } from 'zod'

import type { VizSpec } from '../../vizTypes'

export const barOptionsSchema = z.strictObject({ stack: z.boolean().optional().describe('Stack bars') })

export type BarOptions = z.infer<typeof barOptionsSchema>

export const barSpec: VizSpec<BarOptions> = {
    type: 'bar',
    label: 'Bar chart',
    size: { w: 12, h: 16, minW: 4, minH: 8, stackedRows: { min: 10, max: 16 } },
    optionsSchema: barOptionsSchema,
}
