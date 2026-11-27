import { z } from 'zod'

import type { FilterSpec } from '../filterSpec'

export type SelectFilterConfig = {
    /** What the filter narrows, such as a property name. The host's query runner decides what it means. */
    key: string
    /** The values a person can pick from. Saved with the filter, so a dashboard written as code carries them. */
    options: string[]
}

/** Picked values. A panel keeps rows whose `key` equals any of them. */
export type SelectFilterValue = string[]

export type SelectFilterField = {
    key: string
    label: string
    options: string[]
}

export const SELECT_FILTER_TYPE = 'select'

export function selectFilterSpec(fields: SelectFilterField[]): FilterSpec<SelectFilterConfig> {
    return {
        type: SELECT_FILTER_TYPE,
        addFilterOptions: fields.map(({ key, label, options }) => ({
            label,
            create: () => ({ type: SELECT_FILTER_TYPE, label, config: { key, options } }),
        })),
        configSchema: z.strictObject({ key: z.string().min(1), options: z.array(z.string()) }),
        fieldOf: (config) => config.key,
    }
}
