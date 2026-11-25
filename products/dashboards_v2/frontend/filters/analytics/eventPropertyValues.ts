import { ApiConfig } from 'lib/api'

import { eventsValuesRetrieve } from '~/generated/core/api'

import type { PropertyValues } from '../property/propertyFilterSpec'

/**
 * Recent values of an event property, most common first. Person properties get no suggestions, so they are typed. The
 * API can answer from a stale cache while it refreshes in the background, which `refreshing` passes on.
 */
export const eventPropertyValues: PropertyValues = async ({ key, source }, search, signal) => {
    if (source !== 'event') {
        return []
    }
    const response = await eventsValuesRetrieve(
        String(ApiConfig.getCurrentProjectId()),
        { key, value: search || undefined },
        { signal }
    )
    return {
        options: response.results.map(({ name, count }) => ({ value: name, count })),
        refreshing: response.refreshing,
    }
}
