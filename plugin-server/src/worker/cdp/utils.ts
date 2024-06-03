// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema

import { GroupTypeToColumnIndex, RawClickHouseEvent, Team } from '../../types'
import { clickHouseTimestampToISO } from '../../utils/utils'
import { HogFunctionInvocationContext } from './types'

// that we can keep to as a contract
export function convertToHogFunctionInvocationContext(
    event: RawClickHouseEvent,
    team: Team,
    groupTypes?: GroupTypeToColumnIndex
): HogFunctionInvocationContext {
    const properties = event.properties ? JSON.parse(event.properties) : {}
    if (event.elements_chain) {
        properties['$elements_chain'] = event.elements_chain
    }

    let groups: HogFunctionInvocationContext['groups'] = undefined

    if (groupTypes) {
        groups = {}

        for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
            const groupKey = (properties[`$groups`] || {})[groupType]
            const groupProperties = event[`group${columnIndex}_properties`]

            // TODO: Check that groupProperties always exist if the event is in that group
            if (groupKey && groupProperties) {
                groups[groupType] = {
                    index: columnIndex,
                    key: groupKey,
                    type: groupType,
                    properties: JSON.parse(groupProperties),
                }
            }
        }
    }

    const context: HogFunctionInvocationContext = {
        project: {
            id: team.id,
            name: team.name,
            url: 'TODO',
        },
        event: {
            // TODO: Element chain!
            uuid: event.uuid,
            name: event.event!,
            distinct_id: event.distinct_id,
            properties,
            timestamp: clickHouseTimestampToISO(event.timestamp),
            // TODO: generate url
            url: 'url',
        },
        person: event.person_id
            ? {
                  uuid: event.person_id,
                  properties: event.person_properties ? JSON.parse(event.person_properties) : {},
                  // TODO: This
                  url: 'url',
              }
            : undefined,
        groups,
    }

    return context
}
