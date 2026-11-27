import { z } from 'zod'

import type { VizSpec } from '../../vizTypes'

export const statOptionsSchema = z.strictObject({
    format: z.enum(['number', 'currency', 'percentage']).optional().describe('Format'),
})

export type StatOptions = z.infer<typeof statOptionsSchema>

export const statSpec: VizSpec<StatOptions> = {
    type: 'stat',
    label: 'Number',
    // Eight rows fit the title, the number and the footer.
    size: { w: 6, h: 8, minW: 3, minH: 4 },
    optionsSchema: statOptionsSchema,
}
