import { MakeLogicType, actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { chunk } from 'lib/utils/arrays'

import { ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import { parsePartialJSON, selectAiValue } from './utils'

const AI_DATA_QUERY_TAGS = {
    productKey: ProductKey.AI_OBSERVABILITY,
    scene: 'ai_observability_trace',
}

const EVENT_TIMESTAMP_WINDOW_MINUTES = 10
const BATCH_MAX_SIZE = 100
const BATCH_DEBOUNCE_MS = 0

type AIDataQueryRow = [unknown, unknown, unknown, unknown, unknown, unknown, unknown]

interface AIDataQuerySource {
    from: string
    traceIdExpression: string
    inputExpression: string
    outputExpression: string
    outputChoicesExpression: string
    inputStateExpression: string
    outputStateExpression: string
    toolsExpression: string
}

const AI_EVENTS_SOURCE: AIDataQuerySource = {
    from: 'posthog.ai_events AS ai_events',
    traceIdExpression: 'trace_id',
    inputExpression: 'input',
    outputExpression: 'output',
    outputChoicesExpression: 'output_choices',
    inputStateExpression: 'input_state',
    outputStateExpression: 'output_state',
    toolsExpression: 'tools',
}

const EVENTS_SOURCE: AIDataQuerySource = {
    from: 'events',
    traceIdExpression: 'properties.$ai_trace_id',
    inputExpression: 'properties.$ai_input',
    outputExpression: 'properties.$ai_output',
    outputChoicesExpression: 'properties.$ai_output_choices',
    inputStateExpression: 'properties.$ai_input_state',
    outputStateExpression: 'properties.$ai_output_state',
    toolsExpression: 'properties.$ai_tools',
}

export interface AIData {
    input: unknown
    output: unknown
    tools: unknown
}

export interface AIDataLookup {
    eventId: string
    input: unknown
    output: unknown
    tools: unknown
    traceId?: string
    timestamp?: string
}

function isUsableValue(value: unknown): boolean {
    return value !== null && value !== undefined && value !== '' && value !== 'null'
}

function parseHeavyValue(value: unknown): unknown {
    if (!isUsableValue(value)) {
        return undefined
    }
    if (typeof value !== 'string') {
        return value
    }
    try {
        return JSON.parse(value)
    } catch {
        try {
            return parsePartialJSON(value)
        } catch {
            return value
        }
    }
}

// A column can hold an empty container while a sibling holds the response, so prefer content over
// mere presence — but keep a present-but-empty container, so the caller sees the value arrived and
// the loader does not fall through to the next, slower query for a row it already has.
function selectHeavyValue(...values: unknown[]): unknown {
    return selectAiValue(...values.map(parseHeavyValue))
}

function mapAIDataQueryRow(row: AIDataQueryRow): AIData {
    const [, input, output, outputChoices, inputState, outputState, tools] = row
    return {
        input: selectHeavyValue(input, inputState),
        output: selectHeavyValue(outputChoices, outputState, output),
        tools: parseHeavyValue(tools),
    }
}

function hasLoadedAIData(data: AIData): boolean {
    return isUsableValue(data.input) || isUsableValue(data.output) || isUsableValue(data.tools)
}

function hasInputAndOutput(data: AIData): boolean {
    return data.input != null && data.output != null
}

function mergeAIData(base: AIData, loaded: AIData | null): AIData {
    if (!loaded) {
        return base
    }
    return {
        input: loaded.input ?? base.input,
        output: loaded.output ?? base.output,
        tools: loaded.tools ?? base.tools,
    }
}

function uniqueNonEmpty(values: (string | undefined)[]): string[] {
    return Array.from(new Set(values.filter((value): value is string => !!value)))
}

// One query per source across the whole batch, keyed by event uuid. The scan window is the union
// of every event's ±window, so it stays narrow when the batch's rows are clustered in time.
async function queryAIDataBatch(lookups: AIDataLookup[], source: AIDataQuerySource): Promise<Map<string, AIData>> {
    const traceIds = uniqueNonEmpty(lookups.map((lookup) => lookup.traceId))
    const eventIds = uniqueNonEmpty(lookups.map((lookup) => lookup.eventId))

    const timestamps = lookups
        .map((lookup) => (lookup.timestamp ? dayjs(lookup.timestamp) : null))
        .filter((timestamp): timestamp is Dayjs => !!timestamp && timestamp.isValid())

    if (traceIds.length === 0 || eventIds.length === 0 || timestamps.length === 0) {
        return new Map()
    }

    let earliest = timestamps[0]
    let latest = timestamps[0]
    for (const timestamp of timestamps) {
        if (timestamp.isBefore(earliest)) {
            earliest = timestamp
        }
        if (timestamp.isAfter(latest)) {
            latest = timestamp
        }
    }
    const dateFrom = earliest.subtract(EVENT_TIMESTAMP_WINDOW_MINUTES, 'minute').toISOString()
    const dateTo = latest.add(EVENT_TIMESTAMP_WINDOW_MINUTES, 'minute').toISOString()

    const response = await api.queryHogQL<AIDataQueryRow[]>(
        hogql`
            SELECT
                uuid,
                argMax(ai_input, timestamp) AS ai_input,
                argMax(ai_output, timestamp) AS ai_output,
                argMax(ai_output_choices, timestamp) AS ai_output_choices,
                argMax(ai_input_state, timestamp) AS ai_input_state,
                argMax(ai_output_state, timestamp) AS ai_output_state,
                argMax(ai_tools, timestamp) AS ai_tools
            FROM (
                SELECT
                    toString(uuid) AS uuid,
                    timestamp,
                    ${hogql.raw(source.inputExpression)} AS ai_input,
                    ${hogql.raw(source.outputExpression)} AS ai_output,
                    ${hogql.raw(source.outputChoicesExpression)} AS ai_output_choices,
                    ${hogql.raw(source.inputStateExpression)} AS ai_input_state,
                    ${hogql.raw(source.outputStateExpression)} AS ai_output_state,
                    ${hogql.raw(source.toolsExpression)} AS ai_tools
                FROM ${hogql.raw(source.from)}
                WHERE ${hogql.raw(source.traceIdExpression)} IN ${traceIds}
                  AND toString(uuid) IN ${eventIds}
                  AND timestamp >= toDateTime(${dateFrom})
                  AND timestamp <= toDateTime(${dateTo})
            )
            GROUP BY uuid
            LIMIT ${eventIds.length}
        `,
        { ...AI_DATA_QUERY_TAGS, name: 'ai_observability_event_heavy_props_lookup' }
    )

    const dataByEventId = new Map<string, AIData>()
    for (const row of response.results ?? []) {
        const eventId = row[0] == null ? '' : String(row[0])
        if (!eventId) {
            continue
        }
        const data = mapAIDataQueryRow(row)
        if (hasLoadedAIData(data)) {
            dataByEventId.set(eventId, data)
        }
    }
    return dataByEventId
}

// Resolves every lookup in the batch. Each result starts from the values the main query already
// handed us, then merges anything the heavy-prop lookups add. A lookup that resolves to nothing
// keeps its base values, so the cell stops loading and falls back to what the main query returned.
async function fetchAIDataBatch(lookups: AIDataLookup[]): Promise<Record<string, AIData>> {
    const results: Record<string, AIData> = {}
    const pending: AIDataLookup[] = []

    for (const lookup of lookups) {
        results[lookup.eventId] = { input: lookup.input, output: lookup.output, tools: lookup.tools }

        // Both sides already present, or no trace coordinates to query with — nothing to fetch.
        if (hasInputAndOutput(results[lookup.eventId]) || !lookup.traceId || !lookup.timestamp) {
            continue
        }
        pending.push(lookup)
    }

    if (pending.length === 0) {
        return results
    }

    // Query the dedicated table first. TraceQuery still has a rollout gate, so using it here can
    // repeat the original `events` read and miss stripped heavy props.
    try {
        const aiEventsData = await queryAIDataBatch(pending, AI_EVENTS_SOURCE)
        for (const lookup of pending) {
            results[lookup.eventId] = mergeAIData(results[lookup.eventId], aiEventsData.get(lookup.eventId) ?? null)
        }
    } catch (error) {
        console.warn('[aiObservabilityAIDataLogic] failed to load heavy AI props from ai_events', error)
    }

    const fallback = pending.filter((lookup) => !hasInputAndOutput(results[lookup.eventId]))
    if (fallback.length > 0) {
        try {
            const eventsData = await queryAIDataBatch(fallback, EVENTS_SOURCE)
            for (const lookup of fallback) {
                results[lookup.eventId] = mergeAIData(results[lookup.eventId], eventsData.get(lookup.eventId) ?? null)
            }
        } catch (error) {
            console.warn('[aiObservabilityAIDataLogic] failed to load heavy AI props from events', error)
        }
    }

    return results
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiObservabilityAIDataLogicValues {
    aiDataCache: Record<string, AIData | null>
    isEventLoading: (eventId: string) => boolean
    loadingEventIds: Set<string>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiObservabilityAIDataLogicActions {
    ensureAIDataLoaded: (lookups: AIDataLookup[]) => {
        lookups: AIDataLookup[]
    }
    loadAIDataBatchFailure: (requestedEventIds: string[]) => {
        requestedEventIds: string[]
    }
    loadAIDataBatchSuccess: (
        results: Record<string, AIData>,
        requestedEventIds: string[]
    ) => {
        requestedEventIds: string[]
        results: Record<string, AIData>
    }
    markEventIdsLoading: (eventIds: string[]) => {
        eventIds: string[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiObservabilityAIDataLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        isEventLoading: (loadingEventIds: Set<string>) => (eventId: string) => boolean
    }
}

export type aiObservabilityAIDataLogicType = MakeLogicType<
    aiObservabilityAIDataLogicValues,
    aiObservabilityAIDataLogicActions,
    Record<string, any>,
    aiObservabilityAIDataLogicMeta
>

export const aiObservabilityAIDataLogic = kea<aiObservabilityAIDataLogicType>([
    path(['products', 'ai_observability', 'frontend', 'aiObservabilityAIDataLogic']),

    actions({
        ensureAIDataLoaded: (lookups: AIDataLookup[]) => ({ lookups }),
        markEventIdsLoading: (eventIds: string[]) => ({ eventIds }),
        loadAIDataBatchSuccess: (results: Record<string, AIData>, requestedEventIds: string[]) => ({
            results,
            requestedEventIds,
        }),
        loadAIDataBatchFailure: (requestedEventIds: string[]) => ({ requestedEventIds }),
    }),

    reducers({
        aiDataCache: [
            {} as Record<string, AIData | null>,
            {
                loadAIDataBatchSuccess: (state, { results, requestedEventIds }) => {
                    const next = { ...state }
                    for (const eventId of requestedEventIds) {
                        next[eventId] = results[eventId] ?? null
                    }
                    return next
                },
                loadAIDataBatchFailure: (state, { requestedEventIds }) => {
                    const next = { ...state }
                    for (const eventId of requestedEventIds) {
                        next[eventId] = null
                    }
                    return next
                },
            },
        ],
        loadingEventIds: [
            new Set<string>(),
            {
                markEventIdsLoading: (state, { eventIds }) => {
                    const next = new Set(state)
                    for (const eventId of eventIds) {
                        if (eventId) {
                            next.add(eventId)
                        }
                    }
                    return next
                },
                loadAIDataBatchSuccess: (state, { requestedEventIds }) => {
                    const next = new Set(state)
                    for (const eventId of requestedEventIds) {
                        next.delete(eventId)
                    }
                    return next
                },
                loadAIDataBatchFailure: (state, { requestedEventIds }) => {
                    const next = new Set(state)
                    for (const eventId of requestedEventIds) {
                        next.delete(eventId)
                    }
                    return next
                },
            },
        ],
    }),

    selectors({
        isEventLoading: [
            (s) => [s.loadingEventIds],
            (loadingEventIds: Set<string>): ((eventId: string) => boolean) => {
                return (eventId: string) => loadingEventIds.has(eventId)
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        ensureAIDataLoaded: ({ lookups }) => {
            const uncached = lookups.filter(
                (lookup) =>
                    lookup.eventId &&
                    values.aiDataCache[lookup.eventId] === undefined &&
                    !values.loadingEventIds.has(lookup.eventId)
            )

            if (uncached.length === 0) {
                return
            }

            actions.markEventIdsLoading(uncached.map((lookup) => lookup.eventId))

            const pendingLookups = cache.pendingLookups as Map<string, AIDataLookup>
            for (const lookup of uncached) {
                pendingLookups.set(lookup.eventId, lookup)
            }

            if (cache.batchTimer) {
                return
            }

            cache.batchTimer = setTimeout(async () => {
                const allLookups = Array.from(pendingLookups.values())
                pendingLookups.clear()
                cache.batchTimer = null

                if (allLookups.length === 0) {
                    return
                }

                const chunks = chunk(allLookups, BATCH_MAX_SIZE)

                await Promise.allSettled(
                    chunks.map(async (batch) => {
                        const requestedEventIds = batch.map((lookup) => lookup.eventId)
                        try {
                            const results = await fetchAIDataBatch(batch)
                            actions.loadAIDataBatchSuccess(results, requestedEventIds)
                        } catch (error) {
                            console.warn('[aiObservabilityAIDataLogic] failed to load AI data batch', error)
                            actions.loadAIDataBatchFailure(requestedEventIds)
                        }
                    })
                )
            }, BATCH_DEBOUNCE_MS)
        },
    })),

    events(({ cache }) => ({
        afterMount: () => {
            cache.pendingLookups = new Map<string, AIDataLookup>()
            cache.batchTimer = null
        },
        beforeUnmount: () => {
            if (cache.batchTimer) {
                clearTimeout(cache.batchTimer)
                cache.batchTimer = null
            }
            cache.pendingLookups?.clear?.()
        },
    })),
])
