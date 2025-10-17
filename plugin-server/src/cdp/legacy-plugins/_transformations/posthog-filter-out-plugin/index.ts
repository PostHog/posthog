import { Meta, PluginAttachment, PluginEvent } from '@posthog/plugin-scaffold'

import { parseJSON } from '../../../../utils/json-parse'
import { LegacyTransformationPluginMeta } from '../../types'

export interface Filter {
    property: string
    type: 'string' | 'number' | 'boolean'
    operator: string
    value: string | number | boolean
}

export type PluginMeta = Meta<{
    config: {
        eventsToDrop?: string
        keepUndefinedProperties?: 'Yes' | 'No'
    }
    global: {
        filters: Filter[][] | Filter[]
        eventsToDrop: string[]
        keepUndefinedProperties?: boolean
    }
    attachments: {
        filters?: PluginAttachment
    }
}>

const operations: Record<Filter['type'], Record<string, (a: any, b: any) => boolean>> = {
    string: {
        is: (a, b) => a === b,
        is_not: (a, b) => a !== b,
        contains: (a, b) => a.includes(b),
        not_contains: (a, b) => !a.includes(b),
        regex: (a, b) => new RegExp(b).test(a),
        not_regex: (a, b) => !new RegExp(b).test(a),
    },
    number: {
        gt: (a, b) => a > b,
        lt: (a, b) => a < b,
        gte: (a, b) => a >= b,
        lte: (a, b) => a <= b,
        eq: (a, b) => a === b,
        neq: (a, b) => a !== b,
    },
    boolean: {
        is: (a, b) => a === b,
        is_not: (a, b) => a !== b,
    },
}

export function setupPlugin({ global, config }: LegacyTransformationPluginMeta) {
    if (config.filters) {
        try {
            const filters = typeof config.filters === 'string' ? parseJSON(config.filters) : config.filters
            const filterGroups = parseFiltersAndMigrate(filters)
            if (!filterGroups) {
                throw new Error('No filters found')
            }

            // Check if the filters are valid
            for (const filters of filterGroups) {
                for (const filter of filters) {
                    if (!operations[filter.type][filter.operator]) {
                        throw new Error(
                            `Invalid operator "${filter.operator}" for type "${filter.type}" in filter for "${filter.property}"`
                        )
                    }
                }
            }
            // Save the filters to the global object
            global.filters = filterGroups
        } catch (err) {
            throw new Error('Could not parse filters attachment: ' + err.message)
        }
    } else {
        global.filters = []
    }
    global.eventsToDrop = config?.eventsToDrop?.split(',')?.map((event: string) => event.trim()) || []

    global.keepUndefinedProperties = config.keepUndefinedProperties === 'Yes'
}

export function processEvent(event: PluginEvent, meta: LegacyTransformationPluginMeta): PluginEvent | undefined {
    if (!event.properties) {
        return event
    }
    const { eventsToDrop, keepUndefinedProperties } = meta.global
    const filters = parseFiltersAndMigrate(meta.global.filters)

    // If the event name matches, we drop the event
    if (eventsToDrop.some((e: any) => event.event === e)) {
        return undefined
    }

    // Check if the event satisfies any of the filter groups (OR logic between groups)
    const keepEvent = filters.some((filterGroup) =>
        // Check if all filters in the group are satisfied (AND logic within group)
        filterGroup.every((filter) => {
            const value = event.properties?.[filter.property]
            if (value === undefined) {
                return keepUndefinedProperties
            }

            const operation = operations[filter.type][filter.operator]
            if (!operation) {
                throw new Error(`Invalid operator ${filter.operator}`)
            }

            return operation(value, filter.value)
        })
    )

    // If should keep the event, return it, else return undefined
    return keepEvent ? event : undefined
}

const parseFiltersAndMigrate = (filters: Filter[][] | Filter[]): Filter[][] => {
    if (!Array.isArray(filters)) {
        throw new Error('No filters found')
    }

    // Handle legacy format: Convert single filter array to nested array
    // to maintain backwards compatibility with older plugin versions that used a single array of filters with "AND" logic
    if (filters.length === 0 || !Array.isArray(filters[0])) {
        return [filters as Filter[]]
    }
    return filters as Filter[][]
}
