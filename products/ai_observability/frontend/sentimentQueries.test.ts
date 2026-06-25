import api from 'lib/api'

import { fetchSentimentGenerationsPage, fetchStoredGenerationSentiments } from './sentimentQueries'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

describe('sentimentQueries', () => {
    beforeEach(() => {
        jest.resetAllMocks()
    })

    it('reads stored generation sentiment from ai_events first', async () => {
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValueOnce({
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
        } as any)

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
        jest.spyOn(mockApi, 'queryHogQL')
            .mockResolvedValueOnce({ results: [] } as any)
            .mockResolvedValueOnce({
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
            } as any)

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
        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [['generation-uuid', 'trace-1', null, 'gpt-4.1', 'distinct-1', '2026-06-23T10:00:00Z']],
        } as any)
        jest.spyOn(mockApi, 'queryHogQL')
            .mockResolvedValueOnce({
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
                        '2026-06-23T10:00:01Z',
                    ],
                ],
            } as any)
            .mockResolvedValueOnce({
                results: [
                    ['generation-uuid', 'trace-1', JSON.stringify([{ role: 'user', content: 'this was great' }])],
                ],
            } as any)

        const page = await fetchSentimentGenerationsPage(
            {
                dateFilter: { dateFrom: '-7d', dateTo: null },
                shouldFilterTestAccounts: false,
                propertyFilters: [],
            },
            0
        )

        expect(page.rawCount).toBe(1)
        expect(page.generations).toHaveLength(1)
        expect(page.generations[0]).toMatchObject({
            uuid: 'generation-uuid',
            traceId: 'trace-1',
            aiInput: JSON.stringify([{ role: 'user', content: 'this was great' }]),
            sentiment: {
                label: 'positive',
                score: 0.91,
            },
        })
    })
})
