// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema

import { GroupTypeToColumnIndex, RawClickHouseEvent, Team } from '../types'
import { clickHouseTimestampToISO } from '../utils/utils'
import { HogFunctionFilterGlobals, HogFunctionInvocationGlobals, ParsedClickhouseEvent } from './types'

export const PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES = [
    'email',
    'Email',
    'name',
    'Name',
    'username',
    'Username',
    'UserName',
]

const getPersonDisplayName = (team: Team, distinctId: string, properties: Record<string, any>): string => {
    const personDisplayNameProperties = team.person_display_name_properties ?? PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
    const customPropertyKey = personDisplayNameProperties.find((x) => properties?.[x])
    const propertyIdentifier = customPropertyKey ? properties[customPropertyKey] : undefined

    const customIdentifier: string =
        typeof propertyIdentifier !== 'string' ? JSON.stringify(propertyIdentifier) : propertyIdentifier

    return (customIdentifier || distinctId)?.trim()
}

export function convertToParsedClickhouseEvent(event: RawClickHouseEvent): ParsedClickhouseEvent {
    const properties = event.properties ? JSON.parse(event.properties) : {}
    if (event.elements_chain) {
        properties['$elements_chain'] = event.elements_chain
    }

    return {
        uuid: event.uuid,
        event: event.event,
        team_id: event.team_id,
        distinct_id: event.distinct_id,
        person_id: event.person_id,
        timestamp: clickHouseTimestampToISO(event.timestamp),
        created_at: clickHouseTimestampToISO(event.created_at),
        properties: properties,
        person_created_at: event.person_created_at ? clickHouseTimestampToISO(event.person_created_at) : undefined,
        person_properties: event.person_properties ? JSON.parse(event.person_properties) : {},
        group0_properties: event.group0_properties ? JSON.parse(event.group0_properties) : {},
        group1_properties: event.group1_properties ? JSON.parse(event.group1_properties) : {},
        group2_properties: event.group2_properties ? JSON.parse(event.group2_properties) : {},
        group3_properties: event.group3_properties ? JSON.parse(event.group3_properties) : {},
        group4_properties: event.group4_properties ? JSON.parse(event.group4_properties) : {},
        group0_created_at: event.group0_created_at ? clickHouseTimestampToISO(event.group0_created_at) : undefined,
        group1_created_at: event.group1_created_at ? clickHouseTimestampToISO(event.group1_created_at) : undefined,
        group2_created_at: event.group2_created_at ? clickHouseTimestampToISO(event.group2_created_at) : undefined,
        group3_created_at: event.group3_created_at ? clickHouseTimestampToISO(event.group3_created_at) : undefined,
        group4_created_at: event.group4_created_at ? clickHouseTimestampToISO(event.group4_created_at) : undefined,
    }
}

// that we can keep to as a contract
export function convertToHogFunctionInvocationGlobals(
    event: ParsedClickhouseEvent,
    team: Team,
    siteUrl: string,
    groupTypes?: GroupTypeToColumnIndex
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`
    const properties = event.properties

    let person: HogFunctionInvocationGlobals['person']

    if (event.person_id) {
        const personProperties = event.person_properties
        const personDisplayName = getPersonDisplayName(team, event.distinct_id, personProperties)

        person = {
            uuid: event.person_id,
            name: personDisplayName,
            properties: personProperties,
            url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
        }
    }

    let groups: HogFunctionInvocationGlobals['groups'] = undefined

    if (groupTypes) {
        groups = {}

        for (const [groupType, columnIndex] of Object.entries(groupTypes)) {
            const groupKey = (properties[`$groups`] || {})[groupType]
            const groupProperties = event[`group${columnIndex}_properties`]

            // TODO: Check that groupProperties always exist if the event is in that group
            if (groupKey && groupProperties) {
                const properties = groupProperties

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
            uuid: event.uuid,
            name: event.event!,
            distinct_id: event.distinct_id,
            properties,
            timestamp: event.timestamp,
            url: `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(event.timestamp)}`,
        },
        person,
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
