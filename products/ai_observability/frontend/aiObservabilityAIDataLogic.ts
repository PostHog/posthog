import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { aiObservabilityAIDataLogicType } from './aiObservabilityAIDataLogicType'
import { parseJSONPreview } from './utils'

const AI_DATA_QUERY_TAGS = {
    productKey: ProductKey.AI_OBSERVABILITY,
    scene: 'ai_observability_trace',
}

const EVENT_TIMESTAMP_WINDOW_MINUTES = 10

type AIDataQueryRow = [unknown, unknown, unknown, unknown, unknown, unknown]

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

export interface LoadAIDataParams {
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
    try {
        return parseJSONPreview(value)
    } catch {
        return value
    }
}

function firstUsableValue(...values: unknown[]): unknown {
    for (const value of values) {
        const parsed = parseHeavyValue(value)
        if (isUsableValue(parsed)) {
            return parsed
        }
    }
    return undefined
}

function mapAIDataQueryRow(row: AIDataQueryRow): AIData {
    const [input, output, outputChoices, inputState, outputState, tools] = row
    return {
        input: firstUsableValue(input, inputState),
        output: firstUsableValue(outputChoices, outputState, output),
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

async function queryAIDataForEvent(params: LoadAIDataParams, source: AIDataQuerySource): Promise<AIData | null> {
    if (!params.traceId || !params.timestamp) {
        return null
    }

    const eventTimestamp = dayjs(params.timestamp)
    if (!eventTimestamp.isValid()) {
        return null
    }

    const dateFrom = eventTimestamp.subtract(EVENT_TIMESTAMP_WINDOW_MINUTES, 'minute').toISOString()
    const dateTo = eventTimestamp.add(EVENT_TIMESTAMP_WINDOW_MINUTES, 'minute').toISOString()
    const response = await api.queryHogQL<AIDataQueryRow[]>(
        hogql`
            SELECT
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
                WHERE ${hogql.raw(source.traceIdExpression)} = ${params.traceId}
                  AND toString(uuid) = ${params.eventId}
                  AND timestamp >= toDateTime(${dateFrom})
                  AND timestamp <= toDateTime(${dateTo})
            )
            GROUP BY uuid
            LIMIT 1
        `,
        { ...AI_DATA_QUERY_TAGS, name: 'ai_observability_event_heavy_props_lookup' }
    )

    const row = response.results?.[0]
    if (!row) {
        return null
    }

    const data = mapAIDataQueryRow(row)
    return hasLoadedAIData(data) ? data : null
}

async function loadAIDataAsync(params: LoadAIDataParams): Promise<AIData> {
    const { input, output, tools, traceId, timestamp } = params
    let loadedData: AIData = { input, output, tools }

    // Passthrough: caller already has both sides of the conversation (e.g. the trace page
    // hydrates rows from the TraceQuery that has heavy props merged back). No fetch needed.
    if (input != null && output != null) {
        return { input, output, tools }
    }

    // Can't fetch without trace coordinates — fall back to whatever we were handed.
    // This includes events without $ai_trace_id, which predate the SDK's auto-assignment.
    if (!traceId || !timestamp) {
        return { input, output, tools }
    }

    // Query the dedicated table directly first. TraceQuery still has a rollout gate, so
    // using it here can repeat the original `events` read and miss stripped heavy props.
    try {
        const aiEventsData = await queryAIDataForEvent(params, AI_EVENTS_SOURCE)
        loadedData = mergeAIData(loadedData, aiEventsData)
        if (hasInputAndOutput(loadedData)) {
            return loadedData
        }
    } catch (error) {
        console.warn('[aiObservabilityAIDataLogic] failed to load heavy AI props from ai_events', error)
    }

    try {
        const eventsData = await queryAIDataForEvent(params, EVENTS_SOURCE)
        return mergeAIData(loadedData, eventsData)
    } catch (error) {
        console.warn('[aiObservabilityAIDataLogic] failed to load heavy AI props from events', error)
        return loadedData
    }
}

export const aiObservabilityAIDataLogic = kea<aiObservabilityAIDataLogicType>([
    path(['products', 'ai_observability', 'frontend', 'aiObservabilityAIDataLogic']),

    actions({
        loadAIDataForEvent: (params: LoadAIDataParams) => params,
        clearAIDataForEvent: (eventId: string) => ({ eventId }),
        clearAllAIData: true,
    }),

    reducers({
        aiDataCache: [
            {} as Record<string, AIData>,
            {
                loadAIDataForEventSuccess: (state, { aiDataForEvent }) => ({
                    ...state,
                    [aiDataForEvent.eventId]: {
                        input: aiDataForEvent.input,
                        output: aiDataForEvent.output,
                        tools: aiDataForEvent.tools,
                    },
                }),
                clearAIDataForEvent: (state, { eventId }) => {
                    const { [eventId]: _, ...rest } = state
                    return rest
                },
                clearAllAIData: () => ({}),
            },
        ],
        loadingEventIds: [
            new Set<string>(),
            {
                loadAIDataForEvent: (state, params) => {
                    const newSet = new Set(state)
                    newSet.add(params.eventId)
                    return newSet
                },
                loadAIDataForEventSuccess: (state, { aiDataForEvent }) => {
                    const newSet = new Set(state)
                    newSet.delete(aiDataForEvent.eventId)
                    return newSet
                },
                loadAIDataForEventFailure: (state, params) => {
                    const newSet = new Set(state)
                    const { eventId } = params.errorObject
                    newSet.delete(eventId)
                    return newSet
                },
            },
        ],
    }),

    selectors({
        isEventLoading: [
            (s) => [s.loadingEventIds],
            (loadingEventIds): ((eventId: string) => boolean) => {
                return (eventId: string) => loadingEventIds.has(eventId)
            },
        ],
    }),

    loaders(() => ({
        aiDataForEvent: [
            null as (AIData & { eventId: string }) | null,
            {
                loadAIDataForEvent: async (params: LoadAIDataParams) => {
                    const data = await loadAIDataAsync(params)
                    return {
                        ...data,
                        eventId: params.eventId,
                    }
                },
            },
        ],
    })),
])
