import { ensureStringIsNotBlank } from 'lib/utils/strings'

import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { ActionFilter, EntityFilter, EntityTypes } from '~/types'

export const isAllEventsEntityFilter = (filter: EntityFilter | ActionFilter | null | undefined): boolean => {
    return (
        filter != null &&
        filter.type === EntityTypes.EVENTS &&
        filter.id === null &&
        (!filter.name || filter.name === 'All events')
    )
}

export const formatEventName = (name: string | undefined | null): string | undefined => {
    if (!name) {
        return
    }

    // Handle comma-separated event keys (e.g., "$pageview, $exception" from GroupNode)
    if (name.includes(',')) {
        return name
            .split(',')
            .map((eventName) => {
                const trimmed = eventName.trim()
                return CORE_FILTER_DEFINITIONS_BY_GROUP.events?.[trimmed]?.label || trimmed
            })
            .join(', ')
    }

    return CORE_FILTER_DEFINITIONS_BY_GROUP.events?.[name]?.label || name
}

export const getDisplayNameFromEntityFilter = (
    filter: EntityFilter | ActionFilter | null | undefined,
    isCustom = true
): string | null => {
    // Make sure names aren't blank strings
    const customName = ensureStringIsNotBlank(filter?.custom_name)

    let name = ensureStringIsNotBlank(filter?.name)
    name = formatEventName(name) ?? name

    if (isAllEventsEntityFilter(filter)) {
        name = 'All events'
    }

    // Return custom name. If that doesn't exist then the name, then the id, then just null.
    return (isCustom ? customName : null) ?? name ?? (filter?.id ? `${filter?.id}` : null)
}
