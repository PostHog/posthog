// NOTE: PostIngestionEvent is our context event - it should never be sent directly to an output, but rather transformed into a lightweight schema

import { CyclotronJob, CyclotronJobUpdate } from '@posthog/cyclotron'
import { Bytecodes, ExecResult, HogVMException } from '@posthog/hogvm'
import { DateTime } from 'luxon'
import RE2 from 're2'
import { gunzip, gzip } from 'zlib'

import { RawClickHouseEvent, Team, TimestampFormat } from '../types'
import { safeClickhouseString } from '../utils/db/utils'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { castTimestampOrNow, clickHouseTimestampToISO, UUIDT } from '../utils/utils'
import { MAX_GROUP_TYPES_PER_TEAM } from '../worker/ingestion/group-type-manager'
import { CdpInternalEvent } from './schema'
import { execHog } from './services/hog-executor.service'
import {
    HogFunctionAppMetric,
    HogFunctionCapturedEvent,
    HogFunctionFilterGlobals,
    HogFunctionInvocation,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationLogEntry,
    HogFunctionInvocationQueueParameters,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
    HogFunctionLogEntrySerialized,
    HogFunctionType,
} from './types'
// ID of functions that are hidden from normal users and used by us for special testing
// For example, transformations use this to only run if in comparison mode
export const CDP_TEST_ID = '[CDP-TEST-HIDDEN]'

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
    const properties = event.properties ? parseJSON(event.properties) : {}
    const projectUrl = `${siteUrl}/project/${team.id}`

    let person: HogFunctionInvocationGlobals['person']

    if (event.person_id) {
        const personProperties = event.person_properties ? parseJSON(event.person_properties) : {}
        const personDisplayName = getPersonDisplayName(team, event.distinct_id, personProperties)

        person = {
            id: event.person_id,
            properties: personProperties,
            name: personDisplayName,
            url: `${projectUrl}/person/${encodeURIComponent(event.distinct_id)}`,
        }
    }

    // TRICKY: the timsestamp can sometimes be an ISO for example if coming from the test api
    // so we need to handle that case
    const eventTimestamp = DateTime.fromISO(event.timestamp).isValid
        ? event.timestamp
        : clickHouseTimestampToISO(event.timestamp)

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: event.uuid,
            event: event.event!,
            elements_chain: event.elements_chain,
            distinct_id: event.distinct_id,
            properties,
            timestamp: eventTimestamp,
            url: `${projectUrl}/events/${encodeURIComponent(event.uuid)}/${encodeURIComponent(eventTimestamp)}`,
        },
        person,
    }

    return context
}

export function convertInternalEventToHogFunctionInvocationGlobals(
    data: CdpInternalEvent,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`

    let person: HogFunctionInvocationGlobals['person']

    if (data.person) {
        const personDisplayName = getPersonDisplayName(team, data.event.distinct_id, data.person.properties)

        person = {
            id: data.person.id,
            properties: data.person.properties,
            name: personDisplayName,
            url: data.person.url ?? '',
        }
    }

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: data.event.uuid,
            event: data.event.event,
            elements_chain: '', // Not applicable but left here for compatibility
            distinct_id: data.event.distinct_id,
            properties: data.event.properties,
            timestamp: data.event.timestamp,
            url: data.event.url ?? '',
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
    // Adapted from SQL: arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id="(.*?)"')),
    const idRegex = new RE2(/(?::|")attr_id="(.*?)"/g)
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

    // We need to add default empty groups so that filtering works as it expects it to always exist
    for (let i = 0; i < MAX_GROUP_TYPES_PER_TEAM; i++) {
        groups[`group_${i}`] = {
            key: null,
            index: i,
            properties: {},
        }
    }

    for (const [_groupType, group] of Object.entries(globals.groups || {})) {
        groups[`group_${group.index}`] = {
            key: group.id,
            index: group.index,
            properties: group.properties,
        }
        groups[_groupType] = groups[`group_${group.index}`]
    }

    const elementsChain = globals.event.elements_chain ?? globals.event.properties['$elements_chain']
    const response = {
        ...groups,
        event: globals.event.event,
        elements_chain: elementsChain,
        elements_chain_href: '',
        elements_chain_texts: [] as string[],
        elements_chain_ids: [] as string[],
        elements_chain_elements: [] as string[],
        timestamp: globals.event.timestamp,
        properties: globals.event.properties,
        person: globals.person ? { id: globals.person.id, properties: globals.person.properties } : undefined,
        pdi: globals.person
            ? {
                  distinct_id: globals.event.distinct_id,
                  person_id: globals.person.id,
                  person: { id: globals.person.id, properties: globals.person.properties },
              }
            : undefined,
        distinct_id: globals.event.distinct_id,
    } satisfies HogFunctionFilterGlobals

    // The elements_chain_* fields are stored as materialized columns in ClickHouse.
    // We use the same formula to calculate them here.
    if (elementsChain) {
        const cache: Record<string, any> = {}
        Object.defineProperties(response, {
            elements_chain_href: {
                get: () => {
                    cache.elements_chain_href ??= getElementsChainHref(elementsChain)
                    return cache.elements_chain_href
                },
            },
            elements_chain_texts: {
                get: () => {
                    cache.elements_chain_texts ??= getElementsChainTexts(elementsChain)
                    return cache.elements_chain_texts
                },
            },
            elements_chain_ids: {
                get: () => {
                    cache.elements_chain_ids ??= getElementsChainIds(elementsChain)
                    return cache.elements_chain_ids
                },
            },
            elements_chain_elements: {
                get: () => {
                    cache.elements_chain_elements ??= getElementsChainElements(elementsChain)
                    return cache.elements_chain_elements
                },
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

    return parseJSON(res.toString())
}

export const fixLogDeduplication = (logs: HogFunctionInvocationLogEntry[]): HogFunctionLogEntrySerialized[] => {
    const preparedLogs: HogFunctionLogEntrySerialized[] = []
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
            timestamp: castTimestampOrNow(logEntry.timestamp, TimestampFormat.ClickHouse),
        }
        preparedLogs.push(sanitized)
    })

    return preparedLogs
}

export function createInvocation(
    globals: HogFunctionInvocationGlobalsWithInputs,
    hogFunction: HogFunctionType,
    functionToExecute?: [string, any[]]
): HogFunctionInvocation {
    return {
        id: new UUIDT().toString(),
        globals,
        teamId: hogFunction.team_id,
        hogFunction,
        queue: 'hog',
        priority: 1,
        timings: [],
        functionToExecute,
    }
}

export function serializeHogFunctionInvocation(invocation: HogFunctionInvocation): HogFunctionInvocationSerialized {
    const serializedInvocation: HogFunctionInvocationSerialized = {
        ...invocation,
        hogFunctionId: invocation.hogFunction.id,
        // We clear the params as they are never used in the serialized form
        queueParameters: undefined,
    }

    delete (serializedInvocation as any).hogFunction

    return serializedInvocation
}

function prepareQueueParams(
    _params?: HogFunctionInvocation['queueParameters']
): Pick<CyclotronJobUpdate, 'parameters' | 'blob'> {
    let parameters: HogFunctionInvocation['queueParameters'] = _params
    let blob: CyclotronJobUpdate['blob'] = undefined

    if (!parameters) {
        return { parameters, blob }
    }

    const { body, ...rest } = parameters
    parameters = rest
    blob = body ? Buffer.from(body) : undefined

    return {
        parameters,
        blob,
    }
}

export function invocationToCyclotronJobUpdate(invocation: HogFunctionInvocation): CyclotronJobUpdate {
    const updates = {
        priority: invocation.priority,
        vmState: serializeHogFunctionInvocation(invocation),
        queueName: invocation.queue,
        ...prepareQueueParams(invocation.queueParameters),
    }
    return updates
}

export function cyclotronJobToInvocation(job: CyclotronJob, hogFunction: HogFunctionType): HogFunctionInvocation {
    const parsedState = job.vmState as HogFunctionInvocationSerialized
    const params = job.parameters as HogFunctionInvocationQueueParameters | undefined

    if (job.blob && params) {
        // Deserialize the blob into the params
        try {
            params.body = job.blob ? Buffer.from(job.blob).toString('utf-8') : undefined
        } catch (e) {
            logger.error('Error parsing blob', e, job.blob)
            captureException(e)
        }
    }

    return {
        id: job.id,
        globals: parsedState.globals,
        teamId: hogFunction.team_id,
        hogFunction,
        priority: job.priority,
        queue: (job.queueName as any) ?? 'hog',
        queueParameters: params,
        vmState: parsedState.vmState,
        timings: parsedState.timings,
    }
}

/** Build bytecode that calls a function in another imported bytecode */
export function buildExportedFunctionInvoker(
    exportBytecode: any[],
    exportGlobals: any,
    functionName: string,
    args: any[]
): Bytecodes {
    let argBytecodes: any[] = []
    for (let i = 0; i < args.length; i++) {
        argBytecodes = [
            ...argBytecodes,
            33, // integer
            i + 1, // (index in args array)
            32, // string
            '__args',
            1, // get global
            2, // (chain length)
        ]
    }
    const bytecode = [
        '_H',
        1,
        ...argBytecodes,
        32, // string
        'x',
        2, // call global
        'import',
        1, // (arg count)
        32, // string
        functionName,
        45, // get property
        54, // call local
        args.length,
        35, // pop
    ]
    return {
        bytecodes: {
            x: { bytecode: exportBytecode, globals: exportGlobals },
            root: { bytecode, globals: { __args: args } },
        },
    }
}

export function isLegacyPluginHogFunction(hogFunction: HogFunctionType): boolean {
    return hogFunction.template_id?.startsWith('plugin-') ?? false
}

interface HogFunctionFilterResult {
    match: boolean
    error?: unknown
    logs: HogFunctionInvocationLogEntry[]
    metrics: HogFunctionAppMetric[]
    duration: number
}

/**
 * Shared utility to check if an event matches the filters of a HogFunction.
 * Used by both the HogExecutorService (for destinations) and HogTransformerService (for transformations).
 */
export function checkHogFunctionFilters(options: {
    hogFunction: HogFunctionType
    filterGlobals: HogFunctionFilterGlobals
    /** Optional filters to use instead of those on the function */
    filters?: HogFunctionType['filters']
    /** Whether to enable telemetry for this function at the hogvm level */
    enabledTelemetry?: boolean
    /** The event UUID to use for logging */
    eventUuid?: string
}): HogFunctionFilterResult {
    const { hogFunction, filterGlobals, enabledTelemetry, eventUuid } = options
    const filters = options.filters ?? hogFunction.filters
    const start = performance.now()
    const logs: HogFunctionInvocationLogEntry[] = []
    const metrics: HogFunctionAppMetric[] = []

    let execResult: ExecResult | undefined
    const result: HogFunctionFilterResult = {
        match: false,
        logs,
        metrics,
        duration: 0,
    }

    if (!filters?.bytecode) {
        result.error = 'No filters bytecode'
        return result
    }

    try {
        execResult = execHog(filters.bytecode, {
            globals: filterGlobals,
            telemetry: enabledTelemetry,
        })

        if (execResult.error) {
            throw execResult.error
        }

        result.match = typeof execResult.result === 'boolean' && execResult.result

        if (!result.match) {
            metrics.push({
                team_id: hogFunction.team_id,
                app_source_id: hogFunction.id,
                metric_kind: 'other',
                metric_name: 'filtered',
                count: 1,
            })
        }
    } catch (error) {
        logger.error('🦔', `[HogFunction] Error filtering function`, {
            hogFunctionId: hogFunction.id,
            hogFunctionName: hogFunction.name,
            teamId: hogFunction.team_id,
            error: error.message,
            result: execResult,
        })

        metrics.push({
            team_id: hogFunction.team_id,
            app_source_id: hogFunction.id,
            metric_kind: 'other',
            metric_name: 'filtering_failed',
            count: 1,
        })

        if (eventUuid) {
            logs.push({
                team_id: hogFunction.team_id,
                log_source: 'hog_function',
                log_source_id: hogFunction.id,
                instance_id: new UUIDT().toString(),
                timestamp: DateTime.now(),
                level: 'error',
                message: `Error filtering event ${eventUuid}: ${error.message}`,
            })
        }
        result.error = error.message
    } finally {
        const duration = performance.now() - start

        // Re-using the constant from hog-executor.service.ts
        const DEFAULT_TIMEOUT_MS = 100

        if (duration > DEFAULT_TIMEOUT_MS) {
            logger.error('🦔', `[HogFunction] Filter took longer than expected`, {
                hogFunctionId: hogFunction.id,
                hogFunctionName: hogFunction.name,
                teamId: hogFunction.team_id,
                duration,
                eventId: options?.eventUuid,
            })
        }
    }

    result.duration = performance.now() - start

    return result
}
