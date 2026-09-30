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

export type MatchingFiltersInput = {
    events?: CyclotronJobFilterEvents[]
    actions?: CyclotronJobFilterActions[]
    properties?: CyclotronJobFilterPropertyFilter[]
}

/**
 * Translate cyclotron event filters into a property group that selects the same events in ClickHouse,
 * so a query can count what the matcher would have matched. Each event or action is one OR branch,
 * and the global properties are ANDed over all of them.
 */
export function matchingFiltersToPropertyGroup({
    events,
    actions,
    properties,
}: MatchingFiltersInput): PropertyGroupFilter {
    const seriesProperties: PropertyGroupFilterValue = {
        type: FilterLogicalOperator.Or,
        values: [],
    }
    const propertyGroup: PropertyGroupFilter = {
        type: FilterLogicalOperator.And,
        values: [seriesProperties],
    }

    for (const event of events ?? []) {
        const eventProperties: AnyPropertyFilter[] = [...(event.properties ?? [])]
        if (event.id) {
            eventProperties.push({
                type: PropertyFilterType.HogQL,
                key: hogql`event = ${event.id}`,
            })
        }
        // A branch with no constraints at all would serialize to an empty AND, which matches nothing.
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

    for (const action of actions ?? []) {
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

    if ((properties?.length ?? 0) > 0) {
        propertyGroup.values.push({
            type: FilterLogicalOperator.And,
            values: [...(properties ?? [])] as AnyPropertyFilter[],
        })
    }

    return propertyGroup
}
