import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { HeatmapEventFilter } from './types'

export type HeatmapVariantFilter = {
    flagKey: string
    variant: string
}

const FLAG_CALLED_EVENT = '$feature_flag_called'

// Heatmap rows carry no event properties, so the heatmap keeps the sessions where the flag returned this variant.
export function variantToEventFilter({ flagKey, variant }: HeatmapVariantFilter): HeatmapEventFilter {
    return {
        id: FLAG_CALLED_EVENT,
        name: FLAG_CALLED_EVENT,
        type: 'events',
        order: 0,
        properties: [
            { key: '$feature_flag', value: flagKey, operator: PropertyOperator.Exact, type: PropertyFilterType.Event },
            {
                key: '$feature_flag_response',
                value: variant,
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
    }
}

export function variantFromEventFilters(events: HeatmapEventFilter[] | undefined): HeatmapVariantFilter | null {
    const flagCalled = events?.find((event) => event.id === FLAG_CALLED_EVENT)
    const valueOf = (key: string): unknown => flagCalled?.properties?.find((property) => property.key === key)?.value
    const flagKey = valueOf('$feature_flag')
    const variant = valueOf('$feature_flag_response')
    return typeof flagKey === 'string' && typeof variant === 'string' ? { flagKey, variant } : null
}

// Autocapture events carry the $feature/<key> property, so the clickmap can filter each click directly.
export function variantToElementStatsProperty({ flagKey, variant }: HeatmapVariantFilter): AnyPropertyFilter {
    return {
        key: `$feature/${flagKey}`,
        value: variant,
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    }
}
