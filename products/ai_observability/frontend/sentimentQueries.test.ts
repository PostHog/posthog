import api from 'lib/api'

import {
    fetchSentimentGenerationsPage,
    fetchStoredGenerationSentiments,
    type SentimentCategory,
    type SentimentGenerationsQueryValues,
} from './sentimentQueries'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

const storedSentimentColumns = [
    'trace_id',
    'generation_id',
    'label',
    'score',
    'scores',
    'messages',
    'message_count',
    'evaluation_timestamp',
]
const candidateColumns = ['evaluation_id', 'trace_id', 'generation_id']
const generationColumns = [
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
]

const queryValues: SentimentGenerationsQueryValues = {
    dateFilter: { dateFrom: '-7d', dateTo: null },
    shouldFilterTestAccounts: false,
    activeFilters: new Set<SentimentCategory>(['negative', 'positive']),
    evaluationId: null,
}

function candidateRows(count: number, start: number = 0): unknown[][] {
    return Array.from({ length: count }, (_, index) => {
        const candidateIndex = start + index
        return [`evaluation-${candidateIndex}`, `trace-${candidateIndex}`, `generation-${candidateIndex}`]
    })
}

function generationRow(index: number): unknown[] {
    return [
        `generation-${index}`,
        `trace-${index}`,
        null,
        'gpt-4.1',
        `distinct-${index}`,
        '2026-06-23T10:00:00Z',
        JSON.stringify([{ role: 'user', content: 'this was great' }]),
        'positive',
        '0.91',
        { positive: 0.91, neutral: 0.08, negative: 0.01 },
        {
            '0': {
                label: 'positive',
                score: 0.91,
                scores: { positive: 0.91, neutral: 0.08, negative: 0.01 },
            },
        },
        1,
    ]
}

describe('sentimentQueries', () => {
    beforeEach(() => {
        jest.resetAllMocks()
    })

    it('reads stored generation sentiment from ai_events first', async () => {
        mockApi.queryHogQL.mockResolvedValueOnce({
            columns: storedSentimentColumns,
            results: [
                [
                    'trace-1',
                    'generation-uuid',
                    'positive',
                    '0.91',
                    { positive: 0.91, neutral: 0.08, negative: 0.01 },
                    {
                        '0': {
                            label: 'positive',
                            score: 0.91,
                            scores: { positive: 0.91, neutral: 0.08, negative: 0.01 },
                        },
                    },
                    1,
                    '2026-06-23T10:00:00Z',
                ],
            ],
        })

        const results = await fetchStoredGenerationSentiments([
            {
                key: 'generation-uuid',
                traceId: 'trace-1',
                generationIds: ['generation-uuid'],
            },
        ])

        expect(results['generation-uuid']).toMatchObject({
            label: 'positive',
            score: 0.91,
            message_count: 1,
        })
        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(1)
        const sentimentQuery = mockApi.queryHogQL.mock.calls[0][0]
        expect(sentimentQuery).toContain('FROM posthog.ai_events AS ai_events')
        expect(sentimentQuery).toContain("properties.$ai_evaluation_runtime = 'sentiment'")
        expect(sentimentQuery).toContain('properties.$ai_target_event_id')
        expect(sentimentQuery).not.toContain('properties.$ai_target_id')
        expect(sentimentQuery).not.toContain('properties.$ai_evaluation_result_type')
    })

    it('falls back to events when stored generation sentiment is missing from ai_events', async () => {
        mockApi.queryHogQL
            .mockResolvedValueOnce({ columns: storedSentimentColumns, results: [] })
            .mockResolvedValueOnce({
                columns: storedSentimentColumns,
                results: [
                    [
                        'trace-1',
                        'generation-uuid',
                        'positive',
                        '0.91',
                        { positive: 0.91, neutral: 0.08, negative: 0.01 },
                        {
                            '0': {
                                label: 'positive',
                                score: 0.91,
                                scores: { positive: 0.91, neutral: 0.08, negative: 0.01 },
                            },
                        },
                        1,
                        '2026-06-23T10:00:00Z',
                    ],
                ],
            })

        const results = await fetchStoredGenerationSentiments([
            {
                key: 'generation-uuid',
                traceId: 'trace-1',
                generationIds: ['generation-uuid'],
            },
        ])

        expect(results['generation-uuid']).toMatchObject({
            label: 'positive',
            score: 0.91,
            message_count: 1,
        })
        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(2)
        expect(mockApi.queryHogQL.mock.calls[0][0]).toContain('FROM posthog.ai_events AS ai_events')
        expect(mockApi.queryHogQL.mock.calls[1][0]).toContain('FROM events')
    })

    it('builds sentiment tab rows from evaluated generations and ai_events input', async () => {
        mockApi.queryHogQL
            .mockResolvedValueOnce({
                columns: candidateColumns,
                results: [['evaluation-0', 'trace-0', 'generation-0']],
            })
            .mockResolvedValueOnce({
                columns: generationColumns,
                results: [generationRow(0)],
            })

        const page = await fetchSentimentGenerationsPage(queryValues, 0)

        expect(page.rawCount).toBe(1)
        expect(page.hasMore).toBe(false)
        expect(page.generations).toHaveLength(1)
        expect(page.generations[0]).toMatchObject({
            uuid: 'generation-0',
            traceId: 'trace-0',
            aiInput: JSON.stringify([{ role: 'user', content: 'this was great' }]),
            sentiment: {
                label: 'positive',
                score: 0.91,
            },
        })

        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(2)
        const [candidateQuery, , candidateOptions] = mockApi.queryHogQL.mock.calls[0]
        expect(candidateQuery).toContain("JSONExtractFloat(scores, 'positive')")
        expect(candidateQuery).toContain("JSONExtractFloat(scores, 'negative')")
        expect(candidateQuery).toContain('toIntOrZero(message_count) > 0')
        expect(candidateOptions?.queryParams?.filters).toEqual({
            dateRange: { date_from: '-7d', date_to: null },
        })

        const [, , hydrationOptions] = mockApi.queryHogQL.mock.calls[1]
        expect(hydrationOptions?.queryParams?.filters).toEqual({
            filterTestAccounts: false,
        })
    })

    it('restricts the candidate query to a single evaluation when one is selected', async () => {
        mockApi.queryHogQL
            .mockResolvedValueOnce({ columns: candidateColumns, results: [] })
            .mockResolvedValueOnce({ columns: generationColumns, results: [] })

        await fetchSentimentGenerationsPage({ ...queryValues, evaluationId: 'eval-uuid' }, 0)

        expect(mockApi.queryHogQL.mock.calls[0][0]).toContain("AND properties.$ai_evaluation_id = 'eval-uuid'")
    })

    it.each<[string, SentimentCategory[], string, string]>([
        ['negative only', ['negative'], "label IN ['negative']", "ORDER BY JSONExtractFloat(scores, 'negative') DESC"],
        ['positive only', ['positive'], "label IN ['positive']", "ORDER BY JSONExtractFloat(scores, 'positive') DESC"],
    ])('restricts the candidate query to the selected categories (%s)', async (_, categories, labelClause, order) => {
        mockApi.queryHogQL
            .mockResolvedValueOnce({ columns: candidateColumns, results: [] })
            .mockResolvedValueOnce({ columns: generationColumns, results: [] })

        await fetchSentimentGenerationsPage({ ...queryValues, activeFilters: new Set(categories) }, 0)

        const candidateQuery = mockApi.queryHogQL.mock.calls[0][0]
        expect(candidateQuery).toContain(labelClause)
        expect(candidateQuery).toContain(order)
    })

    it.each<[string, boolean, string | undefined]>([
        ['reuses the cache by default', false, undefined],
        ['forces a recalculation on reload', true, 'force_blocking'],
    ])('%s', async (_, forceRefresh, expectedRefresh) => {
        mockApi.queryHogQL
            .mockResolvedValueOnce({
                columns: candidateColumns,
                results: [['evaluation-0', 'trace-0', 'generation-0']],
            })
            .mockResolvedValueOnce({ columns: generationColumns, results: [generationRow(0)] })

        await fetchSentimentGenerationsPage(queryValues, 0, forceRefresh)

        expect(mockApi.queryHogQL.mock.calls[0][2]?.refresh).toBe(expectedRefresh)
        expect(mockApi.queryHogQL.mock.calls[1][2]?.refresh).toBe(expectedRefresh)
    })

    it('does not fall back to events when ai_events no longer retains a generation input', async () => {
        mockApi.queryHogQL
            .mockResolvedValueOnce({
                columns: candidateColumns,
                results: [['evaluation-0', 'trace-0', 'generation-0']],
            })
            .mockResolvedValueOnce({ columns: generationColumns, results: [] })

        const page = await fetchSentimentGenerationsPage(queryValues, 0)

        expect(page.rawCount).toBe(1)
        expect(page.hasMore).toBe(false)
        expect(page.generations).toEqual([])
        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(2)
    })

    it('backfills candidates removed by generation filters', async () => {
        mockApi.queryHogQL
            .mockResolvedValueOnce({ columns: candidateColumns, results: candidateRows(200) })
            .mockResolvedValueOnce({ columns: generationColumns, results: [] })
            .mockResolvedValueOnce({ columns: candidateColumns, results: candidateRows(1, 200) })
            .mockResolvedValueOnce({ columns: generationColumns, results: [generationRow(200)] })

        const page = await fetchSentimentGenerationsPage(queryValues, 0)

        expect(page.generations).toHaveLength(1)
        expect(page.generations[0].uuid).toBe('generation-200')
        expect(page.rawCount).toBe(201)
        expect(page.hasMore).toBe(false)
        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(4)
        expect(mockApi.queryHogQL.mock.calls[2][0]).toContain('OFFSET 200')
    })
})
