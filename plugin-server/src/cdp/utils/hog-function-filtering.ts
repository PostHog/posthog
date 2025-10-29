import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { ExecResult } from '@posthog/hogvm'

import { HogFlow } from '../../schema/hogflow'
import { RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { createTrackedRE2 } from '../../utils/tracked-re2'
import { UUIDT, clickHouseTimestampToISO } from '../../utils/utils'
import {
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    LogEntry,
    MinimalAppMetric,
} from '../types'
import { execHog } from './hog-exec'

// Module-level constants for fixed regex patterns to avoid recompilation
// These patterns are compiled once at module load and reused for all events
const HREF_REGEX = createTrackedRE2(/(?::|")href="(.*?)"/, undefined, 'hog-filtering:href')
const TEXT_REGEX = createTrackedRE2(/(?::|")text="(.*?)"/g, undefined, 'hog-filtering:text')
const ID_REGEX = createTrackedRE2(/(?::|")attr_id="(.*?)"/g, undefined, 'hog-filtering:id')
const ELEMENT_REGEX = createTrackedRE2(
    /(?:^|;)(a|button|form|input|select|textarea|label)(?:\.|$|:)/g,
    undefined,
    'hog-filtering:element'
)

const hogFunctionFilterDuration = new Histogram({
    name: 'cdp_hog_function_filter_duration_ms',
    help: 'Processing time for filtering a function',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200, 300, 500, 1000],
    labelNames: ['type'],
})

const hogFunctionFilterOutcomes = new Counter({
    name: 'cdp_hog_function_filter_outcome',
    help: 'Count of filter outcomes',
    labelNames: ['result', 'result_type'],
})

const hogFunctionPreFilterCounter = new Counter({
    name: 'cdp_hog_function_prefilter_result',
    help: 'Count of pre-filter results',
    labelNames: ['result'],
})

interface HogFilterResult {
    match: boolean
    error?: unknown
    logs: LogEntry[]
    metrics: MinimalAppMetric[]
}

function getElementsChainHref(elementsChain: string): string {
    // Adapted from SQL: extract(elements_chain, '(?::|\")href="(.*?)"'),
    const hrefMatch = HREF_REGEX.exec(elementsChain)
    return hrefMatch ? hrefMatch[1] : ''
}

function getElementsChainTexts(elementsChain: string): string[] {
    // Adapted from SQL: arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"')),
    const textMatches = new Set<string>()
    // Reset lastIndex for global regex reuse
    TEXT_REGEX.lastIndex = 0
    let textMatch
    while ((textMatch = TEXT_REGEX.exec(elementsChain)) !== null) {
        textMatches.add(textMatch[1])
    }
    return Array.from(textMatches)
}

function getElementsChainIds(elementsChain: string): string[] {
    // Adapted from SQL: arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id="(.*?)"')),
    const idMatches = new Set<string>()
    // Reset lastIndex for global regex reuse
    ID_REGEX.lastIndex = 0
    let idMatch
    while ((idMatch = ID_REGEX.exec(elementsChain)) !== null) {
        idMatches.add(idMatch[1])
    }
    return Array.from(idMatches)
}

function getElementsChainElements(elementsChain: string): string[] {
    // Adapted from SQL: arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
    const elementMatches = new Set<string>()
    // Reset lastIndex for global regex reuse
    ELEMENT_REGEX.lastIndex = 0
    let elementMatch
    while ((elementMatch = ELEMENT_REGEX.exec(elementsChain)) !== null) {
        elementMatches.add(elementMatch[1])
    }
    return Array.from(elementMatches)
}

export function convertClickhouseRawEventToFilterGlobals(event: RawClickHouseEvent): HogFunctionFilterGlobals {
    const properties = event.properties ? parseJSON(event.properties) : {}
    const elementsChain = event.elements_chain ?? properties['$elements_chain']

    // Handle timestamp conversion
    const eventTimestamp = DateTime.fromISO(event.timestamp).isValid
        ? event.timestamp
        : clickHouseTimestampToISO(event.timestamp)

    // Handle person
    let person: HogFunctionFilterGlobals['person'] = null
    let pdi: HogFunctionFilterGlobals['pdi'] = null

    if (event.person_id) {
        const personProperties = event.person_properties ? parseJSON(event.person_properties) : {}

        person = {
            id: event.person_id,
            properties: personProperties,
        }

        pdi = {
            distinct_id: event.distinct_id,
            person_id: event.person_id,
            person: {
                id: event.person_id,
                properties: personProperties,
            },
        }
    }

    // Initialize response with basic structure
    const response: HogFunctionFilterGlobals = {
        event: event.event,
        uuid: event.uuid,
        elements_chain: elementsChain,
        elements_chain_href: '',
        elements_chain_texts: [] as string[],
        elements_chain_ids: [] as string[],
        elements_chain_elements: [] as string[],
        timestamp: eventTimestamp,
        properties,
        person,
        pdi,
        distinct_id: event.distinct_id,
        $group_0: null,
        $group_1: null,
        $group_2: null,
        $group_3: null,
        $group_4: null,
        group_0: { properties: {} },
        group_1: { properties: {} },
        group_2: { properties: {} },
        group_3: { properties: {} },
        group_4: { properties: {} },
    }

    // Handle groups from RawClickHouseEvent
    const groupProperties = [
        event.group0_properties,
        event.group1_properties,
        event.group2_properties,
        event.group3_properties,
        event.group4_properties,
    ]

    groupProperties.forEach((groupPropsString, index) => {
        if (groupPropsString) {
            const groupProps = parseJSON(groupPropsString)
            const groupKey = `group_${index}` as keyof HogFunctionFilterGlobals

            if (groupKey in response) {
                ;(response as any)[groupKey] = {
                    properties: groupProps,
                }
            }
        }
    })

    // Extract group IDs from properties
    for (let i = 0; i < 5; i++) {
        const groupIdKey = `$group_${i}` as keyof HogFunctionFilterGlobals
        const groupIdValue = properties[groupIdKey]

        if (groupIdValue && groupIdKey in response) {
            ;(response as any)[groupIdKey] = groupIdValue
        }
    }

    // Handle elements_chain processing with lazy evaluation
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

export function convertToHogFunctionFilterGlobal(
    globals: Pick<HogFunctionInvocationGlobals, 'event' | 'person' | 'groups'>
): HogFunctionFilterGlobals {
    const elementsChain = globals.event.elements_chain ?? globals.event.properties['$elements_chain']

    const response: HogFunctionFilterGlobals = {
        event: globals.event.event,
        uuid: globals.event.uuid,
        elements_chain: elementsChain,
        elements_chain_href: '',
        elements_chain_texts: [] as string[],
        elements_chain_ids: [] as string[],
        elements_chain_elements: [] as string[],
        timestamp: globals.event.timestamp,
        properties: globals.event.properties,
        person: globals.person ? { id: globals.person.id, properties: globals.person.properties } : null,
        pdi: globals.person
            ? {
                  distinct_id: globals.event.distinct_id,
                  person_id: globals.person.id,
                  person: { id: globals.person.id, properties: globals.person.properties },
              }
            : null,
        distinct_id: globals.event.distinct_id,
        $group_0: null,
        $group_1: null,
        $group_2: null,
        $group_3: null,
        $group_4: null,
        group_0: {
            properties: {},
        },
        group_1: {
            properties: {},
        },
        group_2: {
            properties: {},
        },
        group_3: {
            properties: {},
        },
        group_4: {
            properties: {},
        },
    }

    for (const group of Object.values(globals.groups || {})) {
        // Find the group information and update the relevant properties - NOTE: The typing is tricky here hence the any cast
        const groupKey = `group_${group.index}`

        if (groupKey in response) {
            ;(response as any)[groupKey] = {
                properties: group.properties,
            }
        }

        const groupIdKey = `$group_${group.index}`

        if (groupIdKey in response) {
            ;(response as any)[groupIdKey] = group.id
        }
    }

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

const HOG_FILTERING_TIMEOUT_MS = 100

function preFilterResult(filters: HogFunctionType['filters'], filterGlobals: HogFunctionFilterGlobals): boolean {
    const eventMatches = filters?.events?.some((eventFilter) => {
        // We need to test if the id is null (all events) or if it is in the list of event matchers
        return eventFilter.id === null || eventFilter.id === filterGlobals.event
    })

    // If none of the event filters match we return false
    if (!eventMatches) {
        return false
    }
    // If we get here, there is at least one event filter and it checks this event type
    // hence we say its a match and return true
    return true
}

/**
 * Shared utility to check if an event matches the filters of a HogFunction.
 * Used by both the HogExecutorService (for destinations) and HogTransformerService (for transformations).
 */
export async function filterFunctionInstrumented(options: {
    fn: HogFunctionType | HogFlow
    filterGlobals: HogFunctionFilterGlobals
    /** Optional filters to use instead of those on the function */
    filters: HogFunctionType['filters']
}): Promise<HogFilterResult> {
    const { fn, filters, filterGlobals } = options
    const type = 'type' in fn ? fn.type : 'hogflow'
    const fnKind = 'type' in fn ? 'HogFunction' : 'HogFlow'
    const logs: LogEntry[] = []
    const metrics: MinimalAppMetric[] = []

    let execResult: ExecResult | undefined
    const result: HogFilterResult = {
        match: false,
        logs,
        metrics,
    }

    let preFilterMatch = null

    try {
        // If there are no filters (only bytecode exists then on the filter object)
        // everything matches no need to execute bytecode (lets save those cpu cycles)
        if (filters && Object.keys(filters).length === 1 && 'bytecode' in filters) {
            hogFunctionPreFilterCounter.inc({ result: 'bytecode_execution_skipped__no_filters' })
            result.match = true
            return result
        }

        // check whether we have a match with our pre-filter
        // Only run if we have event filters and NO action filters (as actions are pre-saved event filters)
        if (filters?.events?.length && !filters?.actions?.length) {
            preFilterMatch = preFilterResult(filters, filterGlobals)
            if (preFilterMatch === false) {
                hogFunctionPreFilterCounter.inc({ result: 'bytecode_execution_skipped__pre_filtered_out' })
                result.match = false
                metrics.push({
                    team_id: fn.team_id,
                    app_source_id: fn.id,
                    metric_kind: 'other',
                    metric_name: 'filtered',
                    count: 1,
                })
                return result
            }
        }

        if (!filters?.bytecode) {
            throw new Error('Filters were not compiled correctly and so could not be executed')
        }

        const execHogOutcome = await execHog(filters.bytecode, { globals: filterGlobals })

        if (execHogOutcome) {
            hogFunctionFilterDuration.observe({ type }, execHogOutcome.durationMs)
        }

        if (execHogOutcome.durationMs > HOG_FILTERING_TIMEOUT_MS) {
            logger.error('🦔', `[${fnKind}] Filter took longer than expected`, {
                functionId: fn.id,
                functionName: fn.name,
                teamId: fn.team_id,
                duration: execHogOutcome.durationMs,
                eventId: filterGlobals.uuid,
            })
        }

        execResult = execHogOutcome.execResult

        if (!execHogOutcome.execResult || execHogOutcome.error || execHogOutcome.execResult.error) {
            throw execHogOutcome.error ?? execHogOutcome.execResult?.error ?? new Error('Unknown error')
        }

        // Metric the actual result of the filter to investigate if we get anything other than booleans
        hogFunctionFilterOutcomes.inc({
            result: JSON.stringify(execHogOutcome.execResult.result),
            result_type: typeof execHogOutcome.execResult.result,
        })

        result.match = typeof execHogOutcome.execResult.result === 'boolean' && execHogOutcome.execResult.result

        if (!result.match) {
            metrics.push({
                team_id: fn.team_id,
                app_source_id: fn.id,
                metric_kind: 'other',
                metric_name: 'filtered',
                count: 1,
            })
        }
    } catch (error) {
        logger.debug('🦔', `[${fnKind}] Error filtering function`, {
            functionId: fn.id,
            functionName: fn.name,
            teamId: fn.team_id,
            error: error.message,
            result: execResult,
        })

        metrics.push({
            team_id: fn.team_id,
            app_source_id: fn.id,
            metric_kind: 'other',
            metric_name: 'filtering_failed',
            count: 1,
        })

        logs.push({
            team_id: fn.team_id,
            log_source: fnKind === 'HogFunction' ? 'hog_function' : 'hog_flow',
            log_source_id: fn.id,
            instance_id: new UUIDT().toString(),
            timestamp: DateTime.now(),
            level: 'error',
            message: `Error filtering event ${filterGlobals.uuid ?? ''}: ${error.message}`,
        })
        result.error = error.message
    }
    return result
}
