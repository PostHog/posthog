import api from 'lib/api'

import { HogQLQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { AnyPropertyFilter } from '~/types'

import { normalizeSentimentResult, type GenerationSentiment } from './sentimentResults'

export const GENERATIONS_PAGE_SIZE = 200

const SENTIMENT_QUERY_TAGS = {
    productKey: ProductKey.AI_OBSERVABILITY,
    scene: 'ai_observability_sentiment',
}

const EVALUATION_TARGET_ID_SELECT = `
    ifNull(nullIf(nullIf(toString(properties.$ai_target_event_id), ''), 'null'), '')
`

type StoredSentimentEvaluationQueryRow = [string, string, unknown, unknown, unknown, unknown, unknown, unknown]
type SentimentEvaluationCandidateQueryRow = [string, string, string]
type SentimentGenerationQueryRow = [
    string,
    string,
    unknown,
    unknown,
    unknown,
    unknown,
    unknown,
    unknown,
    unknown,
    unknown,
    unknown,
    unknown,
]

interface SentimentQuerySource {
    from: string
    traceIdExpression: string
}

const AI_EVENTS_SOURCE: SentimentQuerySource = {
    from: 'posthog.ai_events AS ai_events',
    traceIdExpression: 'trace_id',
}

const EVENTS_SOURCE: SentimentQuerySource = {
    from: 'events',
    traceIdExpression: 'properties.$ai_trace_id',
}

interface SentimentEvaluationCandidate {
    evaluationId: string
    traceId: string
    generationId: string
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

async function queryStoredGenerationSentiments(
    normalizedLookups: GenerationSentimentLookup[],
    source: SentimentQuerySource
): Promise<Map<string, GenerationSentiment>> {
    const traceIds = uniqueNonEmpty(normalizedLookups.map((lookup) => lookup.traceId))
    const generationIds = uniqueNonEmpty(normalizedLookups.flatMap((lookup) => lookup.generationIds))

    if (traceIds.length === 0 || generationIds.length === 0) {
        return new Map()
    }

    const response = await api.queryHogQL<StoredSentimentEvaluationQueryRow[]>(
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
    for (const row of response?.results || []) {
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

async function fetchSentimentEvaluationCandidates(
    values: SentimentGenerationsQueryValues,
    offset: number
): Promise<SentimentEvaluationCandidate[]> {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `
            SELECT
                evaluation_id,
                trace_id,
                generation_id
            FROM (
                SELECT
                    properties.$ai_trace_id AS trace_id,
                    ${EVALUATION_TARGET_ID_SELECT} AS generation_id,
                    argMax(toString(uuid), timestamp) AS evaluation_id,
                    argMax(toString(properties.$ai_sentiment_label), timestamp) AS label,
                    argMax(toString(properties.$ai_sentiment_score), timestamp) AS score,
                    max(timestamp) AS evaluation_timestamp
                FROM events
                WHERE event = '$ai_evaluation'
                  AND properties.$ai_evaluation_runtime = 'sentiment'
                  AND timestamp >= now() - INTERVAL 30 DAY
                  AND {filters}
                GROUP BY trace_id, generation_id
            )
            WHERE length(evaluation_id) > 0
              AND length(trace_id) > 0
              AND length(generation_id) > 0
              AND label IN ('positive', 'negative', 'neutral')
            ORDER BY toFloat(score) DESC, evaluation_timestamp DESC, generation_id DESC
            LIMIT ${GENERATIONS_PAGE_SIZE}
            OFFSET ${Math.max(0, Math.trunc(offset))}
        `,
        filters: {
            dateRange: {
                date_from: values.dateFilter.dateFrom,
                date_to: values.dateFilter.dateTo,
            },
        },
        tags: { ...SENTIMENT_QUERY_TAGS, name: 'ai_observability_sentiment_evaluations' },
    }

    const response = await api.query(query)
    const candidates: SentimentEvaluationCandidate[] = []
    for (const row of (response?.results || []) as SentimentEvaluationCandidateQueryRow[]) {
        const [evaluationIdRaw, traceIdRaw, generationIdRaw] = row
        const evaluationId = normalizeString(evaluationIdRaw)
        const traceId = normalizeString(traceIdRaw)
        const generationId = normalizeString(generationIdRaw)

        if (evaluationId && traceId && generationId) {
            candidates.push({ evaluationId, traceId, generationId })
        }
    }
    return candidates
}

async function hydrateSentimentGenerations(
    candidates: SentimentEvaluationCandidate[],
    values: SentimentGenerationsQueryValues
): Promise<SentimentGeneration[]> {
    const traceIds = uniqueNonEmpty(candidates.map((candidate) => candidate.traceId))
    const generationIds = uniqueNonEmpty(candidates.map((candidate) => candidate.generationId))
    const evaluationIds = uniqueNonEmpty(candidates.map((candidate) => candidate.evaluationId))

    if (traceIds.length === 0 || generationIds.length === 0 || evaluationIds.length === 0) {
        return []
    }

    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: hogql`
            SELECT
                generation.uuid,
                generation.trace_id,
                generation.generation_id,
                generation.model,
                generation.distinct_id,
                generation.generation_timestamp,
                generation.ai_input,
                sentiment.label,
                sentiment.score,
                sentiment.scores,
                sentiment.messages,
                sentiment.message_count
            FROM (
                SELECT
                    toString(uuid) AS uuid,
                    trace_id,
                    argMax(generation_id, timestamp) AS generation_id,
                    argMax(model, timestamp) AS model,
                    argMax(distinct_id, timestamp) AS distinct_id,
                    max(timestamp) AS generation_timestamp,
                    argMax(input, timestamp) AS ai_input
                FROM posthog.ai_events
                WHERE event = '$ai_generation'
                  AND trace_id IN ${traceIds}
                  AND toString(uuid) IN ${generationIds}
                  AND {filters}
                GROUP BY uuid, trace_id
            ) AS generation
            INNER JOIN (
                SELECT
                    trace_id,
                    ${hogql.raw(EVALUATION_TARGET_ID_SELECT)} AS generation_id,
                    argMax(toString(properties.$ai_sentiment_label), timestamp) AS label,
                    argMax(toString(properties.$ai_sentiment_score), timestamp) AS score,
                    argMax(properties.$ai_sentiment_scores, timestamp) AS scores,
                    argMax(properties.$ai_sentiment_messages, timestamp) AS messages,
                    argMax(toString(properties.$ai_sentiment_message_count), timestamp) AS message_count
                FROM posthog.ai_events
                WHERE event = '$ai_evaluation'
                  AND properties.$ai_evaluation_runtime = 'sentiment'
                  AND trace_id IN ${traceIds}
                  AND toString(uuid) IN ${evaluationIds}
                GROUP BY trace_id, generation_id
            ) AS sentiment
              ON generation.trace_id = sentiment.trace_id
             AND generation.uuid = sentiment.generation_id
            LIMIT ${generationIds.length}
        `,
        filters: {
            dateRange: {
                date_from: values.dateFilter.dateFrom,
                date_to: values.dateFilter.dateTo,
            },
            filterTestAccounts: values.shouldFilterTestAccounts,
            properties: values.propertyFilters,
        },
        tags: { ...SENTIMENT_QUERY_TAGS, name: 'ai_observability_sentiment_generation_hydration' },
    }

    const response = await api.query(query)
    const generationById = new Map<string, SentimentGeneration>()

    for (const row of (response?.results || []) as SentimentGenerationQueryRow[]) {
        const [
            uuidRaw,
            traceIdRaw,
            generationPropertyIdRaw,
            model,
            distinctId,
            timestampRaw,
            aiInput,
            label,
            score,
            scores,
            messages,
            messageCount,
        ] = row
        const uuid = normalizeString(uuidRaw)
        const traceId = normalizeString(traceIdRaw)
        const timestamp = normalizeString(timestampRaw)
        const sentiment = normalizeSentimentResult({ label, score, scores, messages, message_count: messageCount })

        if (!uuid || !traceId || !timestamp || !sentiment || !hasUsableInput(aiInput)) {
            continue
        }

        generationById.set(uuid, {
            uuid,
            traceId,
            generationIds: uniqueNonEmpty([uuid, normalizeString(generationPropertyIdRaw)]),
            aiInput,
            model: normalizeNullableString(model),
            distinctId: normalizeString(distinctId),
            timestamp,
            createdAt: timestamp,
            sentiment,
        })
    }

    return candidates
        .map((candidate) => generationById.get(candidate.generationId))
        .filter((generation): generation is SentimentGeneration => generation !== undefined)
}

export async function fetchSentimentGenerationsPage(
    values: SentimentGenerationsQueryValues,
    offset: number
): Promise<SentimentGenerationsPage> {
    const candidates = await fetchSentimentEvaluationCandidates(values, offset)
    const generations = await hydrateSentimentGenerations(candidates, values)

    return {
        generations,
        rawCount: candidates.length,
    }
}
