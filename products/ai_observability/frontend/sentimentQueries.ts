import api from 'lib/api'

import { ProductKey, type RefreshType } from '~/queries/schema/schema-general'
import { escapeHogQLString, hogql } from '~/queries/utils'

import { normalizeSentimentResult, type GenerationSentiment } from './sentimentResults'

export const GENERATIONS_PAGE_SIZE = 200

export type SentimentCategory = 'negative' | 'positive'

const SENTIMENT_CATEGORIES: readonly SentimentCategory[] = ['negative', 'positive']

/** The categories the query should select, falling back to all of them if nothing is active */
function resolveActiveCategories(activeFilters: Set<SentimentCategory> | undefined): SentimentCategory[] {
    const active = SENTIMENT_CATEGORIES.filter((category) => activeFilters?.has(category))
    return active.length > 0 ? active : [...SENTIMENT_CATEGORIES]
}

const SENTIMENT_QUERY_TAGS = {
    productKey: ProductKey.AI_OBSERVABILITY,
    scene: 'ai_observability_sentiment',
}

const EVALUATION_TARGET_ID_SELECT = `
    ifNull(nullIf(nullIf(toString(properties.$ai_target_event_id), ''), 'null'), '')
`

const STORED_SENTIMENT_COLUMNS = [
    'trace_id',
    'generation_id',
    'label',
    'score',
    'scores',
    'messages',
    'message_count',
] as const

const SENTIMENT_EVALUATION_CANDIDATE_COLUMNS = ['evaluation_id', 'trace_id', 'generation_id'] as const

const SENTIMENT_GENERATION_COLUMNS = [
    'uuid',
    'trace_id',
    'generation_id',
    'model',
    'distinct_id',
    'generation_timestamp',
    'ai_input',
    'label',
    'score',
    'scores',
    'messages',
    'message_count',
] as const

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
    activeFilters: Set<SentimentCategory>
    /** Restrict results to one sentiment evaluation, or null for all of them */
    evaluationId: string | null
}

export interface SentimentGenerationsPage {
    generations: SentimentGeneration[]
    rawCount: number
    hasMore: boolean
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

function buildQueryColumnIndexes(
    columns: unknown[] | undefined,
    requiredColumns: readonly string[]
): Map<string, number> {
    const availableColumns = (columns ?? []).map(normalizeString)
    const indexes = new Map<string, number>()

    for (const column of requiredColumns) {
        const index = availableColumns.indexOf(column)
        if (index === -1) {
            throw new Error(`Query response is missing the ${column} column`)
        }
        indexes.set(column, index)
    }

    return indexes
}

function queryColumnValue(row: unknown[], columnIndexes: Map<string, number>, column: string): unknown {
    const index = columnIndexes.get(column)
    if (index === undefined) {
        throw new Error(`Query response has no index for the ${column} column`)
    }
    return row[index]
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

    const response = await api.queryHogQL<unknown[][]>(
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

    const columnIndexes = buildQueryColumnIndexes(response.columns, STORED_SENTIMENT_COLUMNS)
    const sentimentByTargetId = new Map<string, GenerationSentiment>()
    for (const row of response.results) {
        const generationId = normalizeString(queryColumnValue(row, columnIndexes, 'generation_id'))
        const normalized = normalizeSentimentResult({
            label: queryColumnValue(row, columnIndexes, 'label'),
            score: queryColumnValue(row, columnIndexes, 'score'),
            scores: queryColumnValue(row, columnIndexes, 'scores'),
            messages: queryColumnValue(row, columnIndexes, 'messages'),
            message_count: queryColumnValue(row, columnIndexes, 'message_count'),
        })

        if (generationId) {
            sentimentByTargetId.set(generationId, normalized)
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
    offset: number,
    refresh?: RefreshType
): Promise<SentimentEvaluationCandidate[]> {
    const categories = resolveActiveCategories(values.activeFilters)
    const categoryScores = categories.map((category) => `JSONExtractFloat(scores, '${category}')`)
    // Rank by the strongest score among the selected categories only, so a deselected
    // category can't push a generation to the top of the page
    const rankingExpression = categoryScores.length > 1 ? `greatest(${categoryScores.join(', ')})` : categoryScores[0]
    const evaluationClause = values.evaluationId
        ? `AND properties.$ai_evaluation_id = ${escapeHogQLString(values.evaluationId)}`
        : ''

    const response = await api.queryHogQL<unknown[][]>(
        hogql`
            SELECT
                evaluation_id,
                trace_id,
                generation_id
            FROM (
                SELECT
                    properties.$ai_trace_id AS trace_id,
                    ${hogql.raw(EVALUATION_TARGET_ID_SELECT)} AS generation_id,
                    argMax(toString(uuid), timestamp) AS evaluation_id,
                    argMax(toString(properties.$ai_sentiment_label), timestamp) AS label,
                    argMax(toString(properties.$ai_sentiment_scores), timestamp) AS scores,
                    argMax(toString(properties.$ai_sentiment_message_count), timestamp) AS message_count,
                    max(timestamp) AS evaluation_timestamp
                FROM events
                WHERE event = '$ai_evaluation'
                  AND properties.$ai_evaluation_runtime = 'sentiment'
                  AND timestamp >= now() - INTERVAL 30 DAY
                  ${hogql.raw(evaluationClause)}
                  AND {filters}
                GROUP BY trace_id, generation_id
            )
            WHERE length(evaluation_id) > 0
              AND length(trace_id) > 0
              AND length(generation_id) > 0
              AND label IN ${categories}
              AND toIntOrZero(message_count) > 0
            ORDER BY ${hogql.raw(rankingExpression)} DESC, evaluation_timestamp DESC, generation_id DESC
            LIMIT ${GENERATIONS_PAGE_SIZE}
            OFFSET ${Math.max(0, Math.trunc(offset))}
        `,
        { ...SENTIMENT_QUERY_TAGS, name: 'ai_observability_sentiment_evaluations' },
        {
            refresh,
            queryParams: {
                filters: {
                    dateRange: {
                        date_from: values.dateFilter.dateFrom,
                        date_to: values.dateFilter.dateTo,
                    },
                    filterTestAccounts: values.shouldFilterTestAccounts,
                },
            },
        }
    )

    const columnIndexes = buildQueryColumnIndexes(response.columns, SENTIMENT_EVALUATION_CANDIDATE_COLUMNS)
    const candidates: SentimentEvaluationCandidate[] = []
    for (const row of response.results) {
        const evaluationId = normalizeString(queryColumnValue(row, columnIndexes, 'evaluation_id'))
        const traceId = normalizeString(queryColumnValue(row, columnIndexes, 'trace_id'))
        const generationId = normalizeString(queryColumnValue(row, columnIndexes, 'generation_id'))

        if (evaluationId && traceId && generationId) {
            candidates.push({ evaluationId, traceId, generationId })
        }
    }
    return candidates
}

/**
 * Fetches the content behind an exact list of generations.
 *
 * This query takes no project filters. The candidate query applies them, and this query needs
 * only the keys that query returns. A person property filter is also far more expensive here:
 * `events` reads person properties from a denormalized column, but `ai_events` resolves them
 * through a join back to the main cluster, which can exhaust query memory.
 */
async function hydrateSentimentGenerations(
    candidates: SentimentEvaluationCandidate[],
    refresh?: RefreshType
): Promise<Map<string, SentimentGeneration>> {
    const traceIds = uniqueNonEmpty(candidates.map((candidate) => candidate.traceId))
    const generationIds = uniqueNonEmpty(candidates.map((candidate) => candidate.generationId))
    const evaluationIds = uniqueNonEmpty(candidates.map((candidate) => candidate.evaluationId))

    if (traceIds.length === 0 || generationIds.length === 0 || evaluationIds.length === 0) {
        return new Map()
    }

    const response = await api.queryHogQL<unknown[][]>(
        hogql`
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
                HAVING message_count != '0'
            ) AS sentiment
              ON generation.trace_id = sentiment.trace_id
             AND generation.uuid = sentiment.generation_id
            LIMIT ${generationIds.length}
        `,
        { ...SENTIMENT_QUERY_TAGS, name: 'ai_observability_sentiment_generation_hydration' },
        { refresh }
    )

    const columnIndexes = buildQueryColumnIndexes(response.columns, SENTIMENT_GENERATION_COLUMNS)
    const generationById = new Map<string, SentimentGeneration>()

    for (const row of response.results) {
        const uuid = normalizeString(queryColumnValue(row, columnIndexes, 'uuid'))
        const traceId = normalizeString(queryColumnValue(row, columnIndexes, 'trace_id'))
        const timestamp = normalizeString(queryColumnValue(row, columnIndexes, 'generation_timestamp'))
        const aiInput = queryColumnValue(row, columnIndexes, 'ai_input')
        const sentiment = normalizeSentimentResult({
            label: queryColumnValue(row, columnIndexes, 'label'),
            score: queryColumnValue(row, columnIndexes, 'score'),
            scores: queryColumnValue(row, columnIndexes, 'scores'),
            messages: queryColumnValue(row, columnIndexes, 'messages'),
            message_count: queryColumnValue(row, columnIndexes, 'message_count'),
        })

        if (!uuid || !traceId || !timestamp || (sentiment.message_count ?? 0) <= 0 || !hasUsableInput(aiInput)) {
            continue
        }

        generationById.set(uuid, {
            uuid,
            traceId,
            generationIds: uniqueNonEmpty([
                uuid,
                normalizeString(queryColumnValue(row, columnIndexes, 'generation_id')),
            ]),
            aiInput,
            model: normalizeNullableString(queryColumnValue(row, columnIndexes, 'model')),
            distinctId: normalizeString(queryColumnValue(row, columnIndexes, 'distinct_id')),
            timestamp,
            createdAt: timestamp,
            sentiment,
        })
    }

    return generationById
}

/**
 * Results are ranked by strongest score and rarely change between visits, so a page load reuses
 * whatever the query cache holds. Pass `forceRefresh` to recompute — that's the Reload button.
 */
export async function fetchSentimentGenerationsPage(
    values: SentimentGenerationsQueryValues,
    offset: number,
    forceRefresh: boolean = false
): Promise<SentimentGenerationsPage> {
    const refresh: RefreshType | undefined = forceRefresh ? 'force_blocking' : undefined
    const generations: SentimentGeneration[] = []
    let rawCount = 0
    let hasMore = false

    while (generations.length < GENERATIONS_PAGE_SIZE) {
        const candidates = await fetchSentimentEvaluationCandidates(values, offset + rawCount, refresh)
        if (candidates.length === 0) {
            break
        }

        const generationById = await hydrateSentimentGenerations(candidates, refresh)
        let consumedCandidates = 0

        for (const candidate of candidates) {
            consumedCandidates++
            const generation = generationById.get(candidate.generationId)
            if (generation) {
                generations.push(generation)
            }
            if (generations.length === GENERATIONS_PAGE_SIZE) {
                break
            }
        }

        rawCount += consumedCandidates
        const consumedEntireBatch = consumedCandidates === candidates.length
        if (generations.length === GENERATIONS_PAGE_SIZE) {
            hasMore = !consumedEntireBatch || candidates.length === GENERATIONS_PAGE_SIZE
            break
        }
        if (candidates.length < GENERATIONS_PAGE_SIZE) {
            break
        }
    }

    return {
        generations,
        rawCount,
        hasMore,
    }
}
