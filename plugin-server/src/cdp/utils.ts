// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema

import { GroupTypeToColumnIndex, RawClickHouseEvent, Team } from '../types'
import { clickHouseTimestampToISO } from '../utils/utils'
import { HogFunctionFilterGlobals, HogFunctionInvocationGlobals } from './types'

// that we can keep to as a contract
export function convertToHogFunctionInvocationGlobals(
    event: RawClickHouseEvent,
    team: Team,
    siteUrl: string,
    groupTypes?: GroupTypeToColumnIndex
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`

    const properties = event.properties ? JSON.parse(event.properties) : {}
    if (event.elements_chain) {
        properties['$elements_chain'] = event.elements_chain
    }

    let groups: HogFunctionInvocationGlobals['groups'] = undefined

    if (groupTypes) {
        groups = {}

        for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
            const groupKey = (properties[`$groups`] || {})[groupType]
            const groupProperties = event[`group${columnIndex}_properties`]

            // TODO: Check that groupProperties always exist if the event is in that group
            if (groupKey && groupProperties) {
                const properties = JSON.parse(groupProperties)

                groups[groupType] = {
                    id: groupKey,
                    index: columnIndex,
                    type: groupType,
                    url: `${projectUrl}/groups/${columnIndex}/${encodeURIComponent(groupKey)}`,
                    properties,
                }
            }
        }
    }
    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            // TODO: Element chain!
            uuid: event.uuid,
            name: event.event!,
            distinct_id: event.distinct_id,
            properties,
            timestamp: clickHouseTimestampToISO(event.timestamp),
            // TODO: generate url
            url: `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(
                clickHouseTimestampToISO(event.timestamp)
            )}`,
        },
        person: event.person_id
            ? {
                  uuid: event.person_id,
                  properties: event.person_properties ? JSON.parse(event.person_properties) : {},
                  // TODO: IS this distinct_id or person_id?
                  url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
              }
            : undefined,
        groups,
    }

    return context
}

export function convertToHogFunctionFilterGlobal(globals: HogFunctionInvocationGlobals): HogFunctionFilterGlobals {
    const groups: Record<string, any> = {}

    for (const [_groupType, group] of Object.entries(globals.groups || {})) {
        groups[`group_${group.index}`] = {
            properties: group.properties,
        }
    }

    return {
        event: globals.event.name,
        elements_chain: globals.event.properties['$elements_chain'],
        timestamp: globals.event.timestamp,
        properties: globals.event.properties,
        person: globals.person ? { properties: globals.person.properties } : undefined,
        ...groups,
    }
}
