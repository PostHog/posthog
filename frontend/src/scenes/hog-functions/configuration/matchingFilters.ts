import { hogql } from '~/queries/utils'
import {
    AnyPropertyFilter,
    CyclotronJobFilterActions,
    CyclotronJobFilterEvents,
    CyclotronJobFilterPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
} from '~/types'

export interface EventMatchingFiltersInput {
    events?: CyclotronJobFilterEvents[]
    actions?: CyclotronJobFilterActions[]
    properties?: CyclotronJobFilterPropertyFilter[]
}

/** Builds a HogQL property group matching any of the given events/actions, ANDed with the given global properties. */
export function buildEventMatchingFilters(filters: EventMatchingFiltersInput | undefined): PropertyGroupFilter {
    const seriesProperties: PropertyGroupFilterValue = {
        type: FilterLogicalOperator.Or,
        values: [],
    }
    const properties: PropertyGroupFilter = {
        type: FilterLogicalOperator.And,
        values: [seriesProperties],
    }

    for (const event of filters?.events ?? []) {
        const eventProperties: AnyPropertyFilter[] = [...(event.properties ?? [])]
        if (event.id) {
            eventProperties.push({
                type: PropertyFilterType.HogQL,
                key: hogql`event = ${event.id}`,
            })
        }
        if (eventProperties.length === 0) {
            eventProperties.push({
                type: PropertyFilterType.HogQL,
                key: 'true',
            })
        }
        seriesProperties.values.push({
            type: FilterLogicalOperator.And,
            values: eventProperties,
        })
    }

    for (const action of filters?.actions ?? []) {
        const actionProperties: AnyPropertyFilter[] = [...(action.properties ?? [])]
        if (action.id) {
            actionProperties.push({
                type: PropertyFilterType.HogQL,
                key: hogql`matchesAction(${parseInt(action.id)})`,
            })
        }
        seriesProperties.values.push({
            type: FilterLogicalOperator.And,
            values: actionProperties,
        })
    }

    if ((filters?.properties?.length ?? 0) > 0) {
        const globalProperties: PropertyGroupFilterValue = {
            type: FilterLogicalOperator.And,
            values: [],
        }
        for (const property of filters?.properties ?? []) {
            globalProperties.values.push(property as AnyPropertyFilter)
        }
        properties.values.push(globalProperties)
    }

    return properties
}
