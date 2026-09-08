import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    FilterIdentifier,
    PersonData,
    aiObservabilityColumnRenderers,
    createPersonFilter,
    getEventData,
    getFilterIdentifier,
    getTracesUrlWithPersonFilter,
} from './aiObservabilityColumnRenderers'
import { llmGenerationSentimentLazyLoaderLogic } from './llmGenerationSentimentLazyLoaderLogic'
import { fetchHasSentimentEvaluations, fetchStoredGenerationSentiments } from './sentimentQueries'
import { GENERATION_SENTIMENT_SELECT } from './sentimentResults'

jest.mock('./sentimentQueries', () => ({
    ...jest.requireActual('./sentimentQueries'),
    fetchHasSentimentEvaluations: jest.fn(),
    fetchStoredGenerationSentiments: jest.fn(),
}))

const mockFetchHasSentimentEvaluations = fetchHasSentimentEvaluations as jest.MockedFunction<
    typeof fetchHasSentimentEvaluations
>
const mockFetchStoredGenerationSentiments = fetchStoredGenerationSentiments as jest.MockedFunction<
    typeof fetchStoredGenerationSentiments
>

describe('aiObservabilityColumnRenderers', () => {
    describe('getEventData', () => {
        // Regression: without traceId + timestamp, useAIData can never fetch stripped heavy props,
        // so Input/Output cells fall back to empty instead of loading the full payload.
        it('extracts trace coordinates from object-format records', () => {
            const eventData = getEventData({
                uuid: 'event-1',
                timestamp: '2026-04-30T10:00:00Z',
                properties: {
                    $ai_trace_id: 'trace-1',
                    $ai_input: [{ role: 'user', content: 'hi' }],
                    $ai_output_choices: [{ role: 'assistant', content: 'hello' }],
                },
            })

            expect(eventData).toEqual({
                uuid: 'event-1',
                input: [{ role: 'user', content: 'hi' }],
                output: [{ role: 'assistant', content: 'hello' }],
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            })
        })

        it('extracts trace coordinates from array-format records by select column position', () => {
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: [
                        'uuid',
                        'properties.$ai_input[-1]',
                        'properties.$ai_output_choices',
                        'properties.$ai_trace_id',
                        'timestamp',
                    ],
                },
            }
            const eventData = getEventData(
                ['event-1', 'stripped-input', 'stripped-output', 'trace-1', '2026-04-30T10:00:00Z'],
                query
            )

            expect(eventData).toEqual({
                uuid: 'event-1',
                input: 'stripped-input',
                output: 'stripped-output',
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            })
        })
    })

    describe('getFilterIdentifier', () => {
        it.each<[string, PersonData | null | undefined, FilterIdentifier | null]>([
            ['returns null when person is null', null, null],
            ['returns null when person is undefined', undefined, null],
            [
                'returns null when person has no identifiable properties',
                { distinct_id: undefined, properties: {} },
                null,
            ],
            [
                'returns email when person has email property',
                { distinct_id: 'user-123', properties: { email: 'test@example.com', username: 'testuser' } },
                { type: 'email', value: 'test@example.com' },
            ],
            [
                'returns username when person has username but no email',
                { distinct_id: 'user-123', properties: { username: 'testuser' } },
                { type: 'username', value: 'testuser' },
            ],
            [
                'returns distinct_id when person has only distinct_id',
                { distinct_id: 'user-123', properties: {} },
                { type: 'distinct_id', value: 'user-123' },
            ],
            [
                'returns distinct_id when properties is undefined',
                { distinct_id: 'user-123' },
                { type: 'distinct_id', value: 'user-123' },
            ],
            [
                'prioritizes email over username and distinct_id',
                { distinct_id: 'user-123', properties: { email: 'test@example.com', username: 'testuser' } },
                { type: 'email', value: 'test@example.com' },
            ],
            [
                'prioritizes username over distinct_id when no email',
                { distinct_id: 'user-123', properties: { username: 'testuser' } },
                { type: 'username', value: 'testuser' },
            ],
            [
                'ignores non-string email property',
                { distinct_id: 'user-123', properties: { email: 123 } },
                { type: 'distinct_id', value: 'user-123' },
            ],
            [
                'ignores non-string username property',
                { distinct_id: 'user-123', properties: { username: ['array'] } },
                { type: 'distinct_id', value: 'user-123' },
            ],
        ])('%s', (_description, person, expected) => {
            expect(getFilterIdentifier(person)).toEqual(expected)
        })
    })

    describe('createPersonFilter', () => {
        it.each<[string, FilterIdentifier, ReturnType<typeof createPersonFilter>]>([
            [
                'creates HogQL filter for distinct_id type',
                { type: 'distinct_id', value: 'user-123' },
                { type: PropertyFilterType.HogQL, key: "distinct_id == 'user-123'" },
            ],
            [
                'creates Person property filter for email type',
                { type: 'email', value: 'test@example.com' },
                {
                    type: PropertyFilterType.Person,
                    key: 'email',
                    operator: PropertyOperator.Exact,
                    value: 'test@example.com',
                },
            ],
            [
                'creates Person property filter for username type',
                { type: 'username', value: 'testuser' },
                {
                    type: PropertyFilterType.Person,
                    key: 'username',
                    operator: PropertyOperator.Exact,
                    value: 'testuser',
                },
            ],
        ])('%s', (_description, filterIdentifier, expected) => {
            expect(createPersonFilter(filterIdentifier)).toEqual(expected)
        })
    })

    describe('getTracesUrlWithPersonFilter', () => {
        it('generates URL with email filter', () => {
            const url = getTracesUrlWithPersonFilter({ type: 'email', value: 'test@example.com' })

            expect(url).toContain('/ai-observability/traces')
            expect(url).toContain('filters')
            expect(url).toContain('email')
            expect(url).toContain('test%40example.com')
        })

        it('generates URL with distinct_id filter', () => {
            const url = getTracesUrlWithPersonFilter({ type: 'distinct_id', value: 'user-123' })

            expect(url).toContain('/ai-observability/traces')
            expect(url).toContain('filters')
            expect(url).toContain("distinct_id%20%3D%3D%20'user-123'")
        })

        it('includes date range params when provided', () => {
            const url = getTracesUrlWithPersonFilter(
                { type: 'email', value: 'test@example.com' },
                { dateFrom: '2024-01-01', dateTo: '2024-01-31' }
            )

            expect(url).toContain('date_from=2024-01-01')
            expect(url).toContain('date_to=2024-01-31')
        })

        it('omits date params when they are null', () => {
            const url = getTracesUrlWithPersonFilter(
                { type: 'email', value: 'test@example.com' },
                { dateFrom: null, dateTo: null }
            )

            expect(url).not.toContain('date_from')
            expect(url).not.toContain('date_to')
        })

        it('handles partial date range', () => {
            const url = getTracesUrlWithPersonFilter(
                { type: 'email', value: 'test@example.com' },
                { dateFrom: '2024-01-01', dateTo: null }
            )

            expect(url).toContain('date_from=2024-01-01')
            expect(url).not.toContain('date_to')
        })
    })
})

// The Sentiment cell used to sit on a skeleton for the whole visit when its query stalled instead
// of erroring, which sent people into traces one by one.
describe('Sentiment column cell', () => {
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: ['uuid', 'properties.$ai_trace_id', GENERATION_SENTIMENT_SELECT, 'timestamp'],
        },
    }
    const record = ['event-1', 'trace-1', '', '2026-04-30T10:00:00Z']

    function renderSentimentCell(): void {
        const SentimentCell = aiObservabilityColumnRenderers[GENERATION_SENTIMENT_SELECT].render!
        render(
            <SentimentCell
                columnName={GENERATION_SENTIMENT_SELECT}
                query={query}
                record={record}
                recordIndex={0}
                rowCount={1}
                value=""
            />
        )
    }

    beforeEach(() => {
        cleanup()
        jest.useFakeTimers()
        initKeaTests()
        llmGenerationSentimentLazyLoaderLogic().mount()
        mockFetchHasSentimentEvaluations.mockResolvedValue(true)
        mockFetchStoredGenerationSentiments.mockReset()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('offers a retry once a stalled lookup passes its deadline', async () => {
        mockFetchStoredGenerationSentiments.mockReturnValue(new Promise(() => {}))

        renderSentimentCell()
        await jest.advanceTimersByTimeAsync(1)
        expect(screen.queryByText('Retry')).toBeNull()

        await jest.advanceTimersByTimeAsync(30000)

        expect(screen.getByText('Retry')).toBeTruthy()
        expect(mockFetchStoredGenerationSentiments).toHaveBeenCalledTimes(1)
    })

    it('looks the sentiment up again when the retry is clicked', async () => {
        mockFetchStoredGenerationSentiments.mockReturnValue(new Promise(() => {}))

        renderSentimentCell()
        await jest.advanceTimersByTimeAsync(30001)

        mockFetchStoredGenerationSentiments.mockResolvedValue({})
        fireEvent.click(screen.getByText('Retry'))
        await jest.advanceTimersByTimeAsync(1)

        expect(mockFetchStoredGenerationSentiments).toHaveBeenCalledTimes(2)
        expect(screen.queryByText('Retry')).toBeNull()
    })

    it('skips the lookup when the project has no sentiment evaluation', async () => {
        mockFetchHasSentimentEvaluations.mockResolvedValue(false)

        renderSentimentCell()
        await jest.advanceTimersByTimeAsync(1)

        expect(mockFetchStoredGenerationSentiments).not.toHaveBeenCalled()
    })
})
