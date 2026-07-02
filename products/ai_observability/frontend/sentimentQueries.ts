import api from 'lib/api'

import { EventsQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { AnyPropertyFilter } from '~/types'

import { normalizeSentimentResult, type GenerationSentiment } from './sentimentResults'

export const GENERATIONS_PAGE_SIZE = 200

const SENTIMENT_QUERY_TAGS = {
    productKey: ProductKey.AI_OBSERVABILITY,
    scene: 'ai_observability_sentiment',
}

const SENTIMENT_GENERATION_SELECT = [
    'uuid',
    'properties.$ai_trace_id',
    'properties.$ai_generation_id',
    'properties.$ai_model',
    'distinct_id',
    'timestamp',
] as const

const EVALUATION_TARGET_ID_SELECT = `
    ifNull(nullIf(nullIf(toString(properties.$ai_target_event_id), ''), 'null'), '')
`

type SentimentEvaluationQueryRow = [string, string, unknown, unknown, unknown, unknown, unknown, unknown]
type GenerationInputQueryRow = [string, string, unknown]

interface SentimentQuerySource {
    from: string
    traceIdExpression: string
}

interface GenerationInputQuerySource extends SentimentQuerySource {
    inputExpression: string
}

const AI_EVENTS_SOURCE: GenerationInputQuerySource = {
    from: 'posthog.ai_events AS ai_events',
    traceIdExpression: 'trace_id',
    inputExpression: 'input',
}

const EVENTS_SOURCE: GenerationInputQuerySource = {
    from: 'events',
    traceIdExpression: 'properties.$ai_trace_id',
    inputExpression: 'properties.$ai_input',
}

export interface GenerationSentimentLookup {
    key: string
    traceId: string
    generationIds: string[]
}

export interface SentimentGeneration {
    uuid: string
    traceId: string
    generationIds: string[]
    aiInput: unknown
    model: string | null
    distinctId: string
    timestamp: string
    /** Earliest event in the trace — used for trace deep-links (matches trace createdAt) */
    createdAt: string
    sentiment: GenerationSentiment | null
}

export interface SentimentGenerationsQueryValues {
    dateFilter: { dateFrom: string | null; dateTo: string | null }
    shouldFilterTestAccounts: boolean
    propertyFilters: AnyPropertyFilter[]
}

export interface SentimentGenerationsPage {
    generations: SentimentGeneration[]
    rawCount: number
}

function normalizeString(value: unknown): string {
    if (value === null || value === undefined) {
        return ''
    }

    const stringValue = String(value)
    return stringValue === 'null' ? '' : stringValue
}

function normalizeNullableString(value: unknown): string | null {
    const stringValue = normalizeString(value)
    return stringValue || null
}

function uniqueNonEmpty(values: string[]): string[] {
    return Array.from(new Set(values.filter(Boolean)))
}

function hasUsableInput(value: unknown): boolean {
    return value !== null && value !== undefined && value !== '' && value !== 'null'
}

function mapGenerationRow(row: unknown[]): SentimentGeneration | null {
    const uuid = normalizeString(row[0])
    const traceId = normalizeString(row[1])

    if (!uuid || !traceId) {
        return null
    }

    const generationPropertyId = normalizeString(row[2])
    const timestamp = normalizeString(row[5])

    return {
        uuid,
        traceId,
        generationIds: uniqueNonEmpty([uuid, generationPropertyId]),
        aiInput: null,
        model: normalizeNullableString(row[3]),
        distinctId: normalizeString(row[4]),
        timestamp,
        createdAt: timestamp,
        sentiment: null,
    }
}

async function queryStoredGenerationSentiments(
    normalizedLookups: GenerationSentimentLookup[],
    source: SentimentQuerySource
): Promise<Map<string, GenerationSentiment>> {
    const traceIds = uniqueNonEmpty(normalizedLookups.map((lookup) => lookup.traceId))
    const generationIds = uniqueNonEmpty(normalizedLookups.flatMap((lookup) => lookup.generationIds))

    if (traceIds.length === 0 || generationIds.length === 0) {
        return new Map()
    }

    const response = await api.queryHogQL<SentimentEvaluationQueryRow[]>(
        hogql`
            SELECT
                trace_id,
                generation_id,
                argMax(label, timestamp) AS label,
                argMax(score, timestamp) AS score,
                argMax(scores, timestamp) AS scores,
                argMax(messages, timestamp) AS messages,
                argMax(message_count, timestamp) AS message_count,
                max(timestamp) AS evaluation_timestamp
            FROM (
                SELECT
                    ${hogql.raw(source.traceIdExpression)} AS trace_id,
                    ${hogql.raw(EVALUATION_TARGET_ID_SELECT)} AS generation_id,
                    timestamp,
                    toString(properties.$ai_sentiment_label) AS label,
                    toString(properties.$ai_sentiment_score) AS score,
                    properties.$ai_sentiment_scores AS scores,
                    properties.$ai_sentiment_messages AS messages,
                    toString(properties.$ai_sentiment_message_count) AS message_count
                FROM ${hogql.raw(source.from)}
                WHERE event = '$ai_evaluation'
                  AND properties.$ai_evaluation_runtime = 'sentiment'
                  AND ${hogql.raw(source.traceIdExpression)} IN ${traceIds}
            )
            WHERE length(generation_id) > 0
              AND generation_id IN ${generationIds}
            GROUP BY trace_id, generation_id
            LIMIT ${Math.max(generationIds.length, 1)}
        `,
        { ...SENTIMENT_QUERY_TAGS, name: 'ai_observability_generation_sentiment_lookup' }
    )

    const sentimentByTargetId = new Map<string, GenerationSentiment>()
    for (const row of response.results || []) {
        const [, generationId, label, score, scores, messages, messageCount] = row
        const normalized = normalizeSentimentResult({
            label,
            score,
            scores,
            messages,
            message_count: messageCount,
        })

        if (generationId && normalized) {
            sentimentByTargetId.set(String(generationId), normalized)
        }
    }

    return sentimentByTargetId
}

function getUnresolvedLookups(
    lookups: GenerationSentimentLookup[],
    sentimentByTargetId: Map<string, GenerationSentiment>
): GenerationSentimentLookup[] {
    return lookups.filter(
        (lookup) => !lookup.generationIds.some((generationId) => sentimentByTargetId.has(generationId))
    )
}

export async function fetchStoredGenerationSentiments(
    lookups: GenerationSentimentLookup[]
): Promise<Record<string, GenerationSentiment | null>> {
    const normalizedLookups = lookups
        .map((lookup) => ({
            key: lookup.key,
            traceId: lookup.traceId,
            generationIds: uniqueNonEmpty(lookup.generationIds),
        }))
        .filter((lookup) => lookup.key && lookup.traceId && lookup.generationIds.length > 0)

    const results: Record<string, GenerationSentiment | null> = {}
    for (const lookup of normalizedLookups) {
        results[lookup.key] = null
    }

    if (normalizedLookups.length === 0) {
        return results
    }

    const sentimentByTargetId = await queryStoredGenerationSentiments(normalizedLookups, AI_EVENTS_SOURCE)
    const fallbackLookups = getUnresolvedLookups(normalizedLookups, sentimentByTargetId)

    if (fallbackLookups.length > 0) {
        const fallbackResults = await queryStoredGenerationSentiments(fallbackLookups, EVENTS_SOURCE)
        for (const [generationId, sentiment] of fallbackResults) {
            sentimentByTargetId.set(generationId, sentiment)
        }
    }

    for (const lookup of normalizedLookups) {
        for (const generationId of lookup.generationIds) {
            const sentiment = sentimentByTargetId.get(generationId)
            if (sentiment) {
                results[lookup.key] = sentiment
                break
            }
        }
    }

    return results
}

async function queryGenerationInputs(
    generations: SentimentGeneration[],
    source: GenerationInputQuerySource
): Promise<Map<string, unknown>> {
    const traceIds = uniqueNonEmpty(generations.map((generation) => generation.traceId))
    const generationEventIds = uniqueNonEmpty(generations.map((generation) => generation.uuid))

    if (traceIds.length === 0 || generationEventIds.length === 0) {
        return new Map()
    }

    const response = await api.queryHogQL<GenerationInputQueryRow[]>(
        hogql`
            SELECT
                uuid,
                trace_id,
                argMax(ai_input, timestamp) AS ai_input
            FROM (
                SELECT
                    toString(uuid) AS uuid,
                    ${hogql.raw(source.traceIdExpression)} AS trace_id,
                    timestamp,
                    ${hogql.raw(source.inputExpression)} AS ai_input
                FROM ${hogql.raw(source.from)}
                WHERE event = '$ai_generation'
                  AND ${hogql.raw(source.traceIdExpression)} IN ${traceIds}
                  AND toString(uuid) IN ${generationEventIds}
            )
            WHERE length(uuid) > 0
              AND length(trace_id) > 0
            GROUP BY uuid, trace_id
            LIMIT ${Math.max(generationEventIds.length, 1)}
        `,
        { ...SENTIMENT_QUERY_TAGS, name: 'ai_observability_generation_input_lookup' }
    )

    const inputs = new Map<string, unknown>()
    for (const [uuid, , aiInput] of response.results || []) {
        if (uuid && hasUsableInput(aiInput)) {
            inputs.set(String(uuid), aiInput)
        }
    }
    return inputs
}

async function fetchGenerationInputs(generations: SentimentGeneration[]): Promise<Record<string, unknown>> {
    const inputsByGenerationKey: Record<string, unknown> = {}
    const missingInputs = generations.filter((generation) => {
        if (hasUsableInput(generation.aiInput)) {
            inputsByGenerationKey[generation.uuid] = generation.aiInput
            return false
        }
        return true
    })

    if (missingInputs.length === 0) {
        return inputsByGenerationKey
    }

    const aiEventsInputs = await queryGenerationInputs(missingInputs, AI_EVENTS_SOURCE)
    for (const [uuid, aiInput] of aiEventsInputs) {
        inputsByGenerationKey[uuid] = aiInput
    }

    const fallbackGenerations = missingInputs.filter((generation) => !aiEventsInputs.has(generation.uuid))
    if (fallbackGenerations.length === 0) {
        return inputsByGenerationKey
    }

    const eventsInputs = await queryGenerationInputs(fallbackGenerations, EVENTS_SOURCE)
    for (const [uuid, aiInput] of eventsInputs) {
        inputsByGenerationKey[uuid] = aiInput
    }

    return inputsByGenerationKey
}

export async function fetchSentimentGenerationsPage(
    values: SentimentGenerationsQueryValues,
    offset: number
): Promise<SentimentGenerationsPage> {
    const generationsQuery: EventsQuery = {
        kind: NodeKind.EventsQuery,
        event: '$ai_generation',
        select: [...SENTIMENT_GENERATION_SELECT],
        orderBy: ['timestamp DESC', 'uuid DESC'],
        after: values.dateFilter.dateFrom || undefined,
        before: values.dateFilter.dateTo || undefined,
        filterTestAccounts: values.shouldFilterTestAccounts,
        properties: values.propertyFilters,
        limit: GENERATIONS_PAGE_SIZE,
        offset,
        tags: { ...SENTIMENT_QUERY_TAGS, name: 'ai_observability_sentiment_generations' },
    }

    const response = await api.query(generationsQuery)
    const generationRows = (response.results || [])
        .map((row) => mapGenerationRow(row))
        .filter((row): row is SentimentGeneration => row !== null)

    const [sentimentByGenerationKey, inputsByGenerationKey] = await Promise.all([
        fetchStoredGenerationSentiments(
            generationRows.map((generation) => ({
                key: generation.uuid,
                traceId: generation.traceId,
                generationIds: generation.generationIds,
            }))
        ),
        fetchGenerationInputs(generationRows),
    ])

    return {
        generations: generationRows
            .map((generation) => ({
                ...generation,
                aiInput: inputsByGenerationKey[generation.uuid] ?? generation.aiInput,
                sentiment: sentimentByGenerationKey[generation.uuid] ?? null,
            }))
            .filter((generation) => generation.sentiment !== null),
        rawCount: response.results?.length ?? 0,
    }
}
