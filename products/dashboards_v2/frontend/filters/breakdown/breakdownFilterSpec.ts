import { z } from 'zod'

import type { FilterSpec } from '../filterSpec'

/** A property to split by. `type` says where it lives, such as `event` or `person`; the host's query runner reads it. */
export type BreakdownOption = { type: string; key: string; label: string }

export type BreakdownFilterConfig = {
    /** The properties a person can split charts by. Saved with the filter, so a dashboard written as code carries them. */
    options: BreakdownOption[]
}

export type BreakdownFilterValue = { type: string; key: string }

export const BREAKDOWN_FILTER_TYPE = 'breakdown'

export function breakdownFilterSpec(options: BreakdownOption[]): FilterSpec<BreakdownFilterConfig> {
    return {
        type: BREAKDOWN_FILTER_TYPE,
        addFilterOptions: [
            {
                label: 'Breakdown',
                create: () => ({ type: BREAKDOWN_FILTER_TYPE, label: 'Breakdown', config: { options } }),
            },
        ],
        configSchema: z.strictObject({
            options: z
                .array(z.strictObject({ type: z.string().min(1), key: z.string().min(1), label: z.string().min(1) }))
                .min(1),
        }),
        // A chart splits by one property at a time, so a dashboard holds one breakdown.
        fieldOf: () => BREAKDOWN_FILTER_TYPE,
    }
}
