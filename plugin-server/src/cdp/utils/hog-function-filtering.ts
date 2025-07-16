import { ExecResult } from '@posthog/hogvm'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'
import RE2 from 're2'

import { HogFlow } from '../../schema/hogflow'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import {
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    LogEntry,
    MinimalAppMetric,
} from '../types'
import { execHog } from './hog-exec'

const hogFunctionFilterDuration = new Histogram({
    name: 'cdp_hog_function_filter_duration_ms',
    help: 'Processing time for filtering a function',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
    labelNames: ['type'],
})

interface HogFilterResult {
    match: boolean
    error?: unknown
    logs: LogEntry[]
    metrics: MinimalAppMetric[]
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

export function convertToHogFunctionFilterGlobal(
    globals: Pick<HogFunctionInvocationGlobals, 'event' | 'person' | 'groups'>
): HogFunctionFilterGlobals {
    const elementsChain = globals.event.elements_chain ?? globals.event.properties['$elements_chain']

    const response: HogFunctionFilterGlobals = {
        event: globals.event.event,
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
/**
 * Shared utility to check if an event matches the filters of a HogFunction.
 * Used by both the HogExecutorService (for destinations) and HogTransformerService (for transformations).
 */
export async function filterFunctionInstrumented(options: {
    fn: HogFunctionType | HogFlow
    filterGlobals: HogFunctionFilterGlobals
    /** Optional filters to use instead of those on the function */
    filters: HogFunctionType['filters']
    /** Whether to enable telemetry for this function at the hogvm level */
    enabledTelemetry?: boolean
    /** The event UUID to use for logging */
    eventUuid?: string
}): Promise<HogFilterResult> {
    const { fn, filters, filterGlobals, enabledTelemetry, eventUuid } = options
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

    try {
        if (!filters?.bytecode) {
            throw new Error('Filters were not compiled correctly and so could not be executed')
        }

        const execHogOutcome = await execHog(filters.bytecode, {
            globals: filterGlobals,
            telemetry: enabledTelemetry,
        })

        if (execHogOutcome) {
            hogFunctionFilterDuration.observe({ type }, execHogOutcome.durationMs)
        }

        if (execHogOutcome.durationMs > HOG_FILTERING_TIMEOUT_MS) {
            logger.error('🦔', `[${fnKind}] Filter took longer than expected`, {
                functionId: fn.id,
                functionName: fn.name,
                teamId: fn.team_id,
                duration: execHogOutcome.durationMs,
                eventId: options?.eventUuid,
            })
        }

        execResult = execHogOutcome.execResult

        if (!execHogOutcome.execResult || execHogOutcome.error || execHogOutcome.execResult.error) {
            throw execHogOutcome.error ?? execHogOutcome.execResult?.error ?? new Error('Unknown error')
        }

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
            message: `Error filtering event ${eventUuid}: ${error.message}`,
        })
        result.error = error.message
    }
    return result
}
