import { z } from 'zod'

import type { FilterSpec } from '../filterSpec'
import type { LoadedOptions } from '../useSearchedOptions'
import type { ValueOption } from '../ValueList'
import type { PropertyCondition } from './propertyOperators'

export type PropertyFilterSource = 'event' | 'person'

export interface PropertyFilterConfig {
    key: string
    source: PropertyFilterSource
}

/** The conditions a person picked, such as "is not Chrome" and "contains Safari". All of them must hold. */
export type PropertyFilterValue = PropertyCondition[]

export interface FeaturedProperty {
    key: string
    label: string
    source?: PropertyFilterSource
}

export type PropertyValues = (
    config: PropertyFilterConfig,
    search: string,
    signal: AbortSignal
) => Promise<LoadedOptions<ValueOption>>

export const PROPERTY_FILTER_TYPE = 'property'

export function propertyFilterSpec(
    featured: FeaturedProperty[],
    pickerLabel?: string
): FilterSpec<PropertyFilterConfig> {
    return {
        type: PROPERTY_FILTER_TYPE,
        addMenuItems: featured.map(({ key, label, source = 'event' }) => ({
            label,
            create: () => ({ type: PROPERTY_FILTER_TYPE, label, config: { key, source } }),
        })),
        pickerLabel,
        configSchema: z.strictObject({ key: z.string().min(1), source: z.enum(['event', 'person']) }),
        fieldOf: (config) => `${config.source}:${config.key}`,
    }
}
