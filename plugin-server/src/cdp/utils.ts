// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema

import { DateTime } from 'luxon'
import RE2 from 're2'
import { gunzip, gzip } from 'zlib'

import { RawClickHouseEvent, Team, TimestampFormat } from '../types'
import { safeClickhouseString } from '../utils/db/utils'
import { castTimestampOrNow, clickHouseTimestampToISO, UUIDT } from '../utils/utils'
import {
    HogFunctionCapturedEvent,
    HogFunctionFilterGlobals,
    HogFunctionInvocation,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionLogEntrySerialized,
    HogFunctionType,
} from './types'

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

// that we can keep to as a contract
export function convertToHogFunctionInvocationGlobals(
    event: RawClickHouseEvent,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const properties = event.properties ? JSON.parse(event.properties) : {}
    if (event.elements_chain) {
        properties['$elements_chain'] = event.elements_chain
    }

    const projectUrl = `${siteUrl}/project/${team.id}`

    let person: HogFunctionInvocationGlobals['person']

    if (event.person_id) {
        const personProperties = event.person_properties ? JSON.parse(event.person_properties) : {}
        const personDisplayName = getPersonDisplayName(team, event.distinct_id, personProperties)

        person = {
            uuid: event.person_id,
            name: personDisplayName,
            properties: personProperties,
            url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
        }
    }

    const eventTimestamp = clickHouseTimestampToISO(event.timestamp)

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
            timestamp: eventTimestamp,
            url: `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(eventTimestamp)}`,
        },
        person,
    }

    return context
}

function getElementsChainHref(elementsChain: string): string {
    // Adapted from SQL: extract(elements_chain, '(?::|\")href="(.*?)"'),
    const hrefRegex = new RE2(/(?::|")href="(.*?)"/)
    const hrefMatch = hrefRegex.exec(elementsChain)
    return hrefMatch ? hrefMatch[1] : ''
}

function getElementsChainTexts(elementsChain: string): string[] {
    // Adapted from SQL: arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"')),
    const textRegex = new RE2(/(?::|")text="(.*?)"/g)
    const textMatches = new Set<string>()
    let textMatch
    while ((textMatch = textRegex.exec(elementsChain)) !== null) {
        textMatches.add(textMatch[1])
    }
    return Array.from(textMatches)
}

function getElementsChainIds(elementsChain: string): string[] {
    // Adapted from SQL: arrayDistinct(extractAll(elements_chain, '(?::|\")id="(.*?)"')),
    const idRegex = new RE2(/(?::|")id="(.*?)"/g)
    const idMatches = new Set<string>()
    let idMatch
    while ((idMatch = idRegex.exec(elementsChain)) !== null) {
        idMatches.add(idMatch[1])
    }
    return Array.from(idMatches)
}

function getElementsChainElements(elementsChain: string): string[] {
    // Adapted from SQL: arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
    const elementRegex = new RE2(/(?:^|;)(a|button|form|input|select|textarea|label)(?:\.|$|:)/g)
    const elementMatches = new Set<string>()
    let elementMatch
    while ((elementMatch = elementRegex.exec(elementsChain)) !== null) {
        elementMatches.add(elementMatch[1])
    }
    return Array.from(elementMatches)
}

export function convertToHogFunctionFilterGlobal(globals: HogFunctionInvocationGlobals): HogFunctionFilterGlobals {
    const groups: Record<string, any> = {}

    for (const [_groupType, group] of Object.entries(globals.groups || {})) {
        groups[`group_${group.index}`] = {
            properties: group.properties,
        }
    }

    const elementsChain = globals.event.properties['$elements_chain']
    const response = {
        event: globals.event.name,
        elements_chain: elementsChain,
        elements_chain_href: '',
        elements_chain_texts: [] as string[],
        elements_chain_ids: [] as string[],
        elements_chain_elements: [] as string[],
        timestamp: globals.event.timestamp,
        properties: globals.event.properties,
        person: globals.person ? { properties: globals.person.properties } : undefined,
        ...groups,
    } satisfies HogFunctionFilterGlobals

    if (elementsChain) {
        // The elements_chain_* fields are stored as materialized columns in ClickHouse.
        // We use the same formula to calculate them here, and make them lazy-loaded.
        Object.defineProperties(response, {
            elements_chain_href: {
                get: () => (response.elements_chain_href = getElementsChainHref(elementsChain)),
            },
            elements_chain_texts: {
                get: () => (response.elements_chain_texts = getElementsChainTexts(elementsChain)),
            },
            elements_chain_ids: {
                get: () => (response.elements_chain_ids = getElementsChainIds(elementsChain)),
            },
            elements_chain_elements: {
                get: () => (response.elements_chain_elements = getElementsChainElements(elementsChain)),
            },
        })
    }
    return response
}

export const convertToCaptureEvent = (event: HogFunctionCapturedEvent, team: Team): any => {
    return {
        uuid: new UUIDT().toString(),
        distinct_id: safeClickhouseString(event.distinct_id),
        data: JSON.stringify({
            event: event.event,
            distinct_id: event.distinct_id,
            properties: event.properties,
            timestamp: event.timestamp,
        }),
        now: DateTime.now().toISO(),
        sent_at: DateTime.now().toISO(),
        token: team.api_token,
    }
}

export const gzipObject = async <T extends object>(object: T): Promise<string> => {
    const payload = JSON.stringify(object)
    const buffer = await new Promise<Buffer>((res, rej) =>
        gzip(payload, (err, result) => (err ? rej(err) : res(result)))
    )
    const res = buffer.toString('base64')

    // NOTE: Base64 encoding isn't as efficient but we would need to change the kafka producer/consumers to use ucs2 or something
    // as well in order to support binary data better

    return res
}

export const unGzipObject = async <T extends object>(data: string): Promise<T> => {
    const res = await new Promise<Buffer>((res, rej) =>
        gunzip(Buffer.from(data, 'base64'), (err, result) => (err ? rej(err) : res(result)))
    )

    return JSON.parse(res.toString())
}

export const prepareLogEntriesForClickhouse = (
    result: HogFunctionInvocationResult
): HogFunctionLogEntrySerialized[] => {
    const preparedLogs: HogFunctionLogEntrySerialized[] = []
    const logs = result.logs
    result.logs = [] // Clear it to ensure it isn't passed on anywhere else

    const sortedLogs = logs.sort((a, b) => a.timestamp.toMillis() - b.timestamp.toMillis())

    if (sortedLogs.length === 0) {
        return []
    }

    // Start with a timestamp that is guaranteed to be before the first log entry
    let previousTimestamp = sortedLogs[0].timestamp.minus(1)

    sortedLogs.forEach((logEntry) => {
        // TRICKY: The clickhouse table dedupes logs with the same timestamp - we need to ensure they are unique by simply plus-ing 1ms
        // if the timestamp is the same as the previous one
        if (logEntry.timestamp <= previousTimestamp) {
            logEntry.timestamp = previousTimestamp.plus(1)
        }

        previousTimestamp = logEntry.timestamp

        const sanitized: HogFunctionLogEntrySerialized = {
            ...logEntry,
            team_id: result.invocation.teamId,
            log_source: 'hog_function',
            log_source_id: result.invocation.hogFunction.id,
            instance_id: result.invocation.id,
            timestamp: castTimestampOrNow(logEntry.timestamp, TimestampFormat.ClickHouse),
        }
        preparedLogs.push(sanitized)
    })

    return preparedLogs
}

export function createInvocation(
    globals: HogFunctionInvocationGlobals,
    hogFunction: HogFunctionType
): HogFunctionInvocation {
    // Add the source of the trigger to the globals
    const modifiedGlobals: HogFunctionInvocationGlobals = {
        ...globals,
        source: {
            name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
            url: `${globals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
        },
    }

    return {
        id: new UUIDT().toString(),
        globals: modifiedGlobals,
        teamId: hogFunction.team_id,
        hogFunction,
        queue: 'hog',
        timings: [],
    }
}
