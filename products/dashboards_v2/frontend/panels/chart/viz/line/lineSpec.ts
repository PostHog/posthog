import { z } from 'zod'

import type { VizSpec } from '../../vizTypes'

export const lineOptionsSchema = z.strictObject({})

export type LineOptions = z.infer<typeof lineOptionsSchema>

export const lineSpec: VizSpec<LineOptions> = {
    type: 'line',
    label: 'Line chart',
    size: { w: 12, h: 16, minW: 4, minH: 8, stackedRows: { min: 10, max: 16 } },
    optionsSchema: lineOptionsSchema,
}
