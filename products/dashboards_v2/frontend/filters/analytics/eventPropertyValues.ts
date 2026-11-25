import { ApiConfig } from 'lib/api'

import { eventsValuesRetrieve } from '~/generated/core/api'

import type { PropertyValues } from '../property/propertyFilterSpec'

/** Recent values of an event property, most common first. Person properties get no suggestions, so they are typed. */
export const eventPropertyValues: PropertyValues = async ({ key, source }, search, signal) => {
    if (source !== 'event') {
        return []
    }
    const response = await eventsValuesRetrieve(
        String(ApiConfig.getCurrentProjectId()),
        { key, value: search || undefined },
        { signal }
    )
    return response.results.map(({ name, count }) => ({ value: name, count }))
}
