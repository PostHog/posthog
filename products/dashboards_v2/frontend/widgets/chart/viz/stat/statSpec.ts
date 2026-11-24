import { z } from 'zod'

import type { VizSpec } from '../../vizTypes'

export const statOptionsSchema = z.strictObject({
    format: z.enum(['number', 'currency', 'percentage']).optional().describe('Format'),
})

export type StatOptions = z.infer<typeof statOptionsSchema>

export const statSpec: VizSpec<StatOptions> = {
    type: 'stat',
    label: 'Number',
    size: { w: 6, h: 6, minW: 3, minH: 4 },
    optionsSchema: statOptionsSchema,
}
