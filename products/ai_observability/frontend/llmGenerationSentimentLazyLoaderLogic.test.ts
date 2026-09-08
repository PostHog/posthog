import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmGenerationSentimentLazyLoaderLogic } from './llmGenerationSentimentLazyLoaderLogic'
import { fetchHasSentimentEvaluations, fetchStoredGenerationSentiments } from './sentimentQueries'
import type { GenerationSentiment } from './sentimentResults'

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

describe('llmGenerationSentimentLazyLoaderLogic', () => {
    let logic: ReturnType<typeof llmGenerationSentimentLazyLoaderLogic.build>

    const sentiment: GenerationSentiment = {
        label: 'positive',
        score: 0.9,
        scores: { positive: 0.9, neutral: 0.08, negative: 0.02 },
        messages: {},
        message_count: 1,
    }

    beforeEach(() => {
        initKeaTests()
        mockFetchHasSentimentEvaluations.mockReset().mockResolvedValue(true)
        mockFetchStoredGenerationSentiments.mockReset().mockResolvedValue({})
        logic = llmGenerationSentimentLazyLoaderLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('starts with an empty cache and loading set', () => {
        expect(logic.values.sentimentByGenerationKey).toEqual({})
        expect(logic.values.loadingGenerationKeys).toEqual(new Set())
    })

    it('marks a generation as loading when queued', async () => {
        await expectLogic(logic, () => {
            logic.actions.ensureGenerationSentimentLoaded({
                key: 'event-uuid-1',
                traceId: 'trace-1',
                generationIds: ['event-uuid-1'],
                timestamp: '2026-06-23T10:00:00Z',
            })
        }).toMatchValues({
            loadingGenerationKeys: new Set(['event-uuid-1']),
        })
    })

    it('stores successful sentiment results by lookup key', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadGenerationSentimentBatchSuccess({ 'event-uuid-1': sentiment }, ['event-uuid-1'])
        }).toMatchValues({
            sentimentByGenerationKey: {
                'event-uuid-1': sentiment,
            },
        })
    })

    it('stores null for requested generations without results', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadGenerationSentimentBatchSuccess({}, ['event-uuid-1', 'event-uuid-2'])
        }).toMatchValues({
            sentimentByGenerationKey: {
                'event-uuid-1': null,
                'event-uuid-2': null,
            },
        })
    })

    it('offers a retry after a failure instead of resolving the cell to no sentiment', async () => {
        logic.actions.ensureGenerationSentimentLoaded({
            key: 'event-uuid-1',
            traceId: 'trace-1',
            generationIds: ['event-uuid-1'],
            timestamp: '2026-06-23T10:00:00Z',
        })

        await expectLogic(logic, () => {
            logic.actions.loadGenerationSentimentBatchFailure(['event-uuid-1'])
        }).toMatchValues({
            loadingGenerationKeys: new Set(),
            sentimentByGenerationKey: {},
        })
        expect(logic.values.didGenerationSentimentLoadFail('event-uuid-1')).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.ensureGenerationSentimentLoaded({
                key: 'event-uuid-1',
                traceId: 'trace-1',
                generationIds: ['event-uuid-1'],
                timestamp: '2026-06-23T10:00:00Z',
            })
        }).toMatchValues({
            loadingGenerationKeys: new Set(['event-uuid-1']),
        })
        expect(logic.values.didGenerationSentimentLoadFail('event-uuid-1')).toBe(false)
    })

    it('drops cached sentiment on reset, so refresh fetches it again', async () => {
        logic.actions.loadGenerationSentimentBatchSuccess({ 'event-uuid-1': sentiment }, ['event-uuid-1'])

        await expectLogic(logic, () => {
            logic.actions.resetGenerationSentiments()
        }).toMatchValues({
            sentimentByGenerationKey: {},
            loadingGenerationKeys: new Set(),
        })
    })

    // Clearing the cells is not enough on its own: the lookup can still be answered from the query
    // cache, which left a freshly scored generation reading as no sentiment after a refresh.
    it('recalculates the first lookup after a reset, then reuses the cache again', async () => {
        jest.useFakeTimers()

        logic.actions.ensureGenerationSentimentLoaded({
            key: 'event-uuid-1',
            traceId: 'trace-1',
            generationIds: ['event-uuid-1'],
            timestamp: '2026-06-23T10:00:00Z',
        })
        await jest.advanceTimersByTimeAsync(1)

        expect(mockFetchStoredGenerationSentiments).toHaveBeenLastCalledWith(
            expect.anything(),
            expect.anything(),
            false
        )

        logic.actions.resetGenerationSentiments()
        logic.actions.ensureGenerationSentimentLoaded({
            key: 'event-uuid-1',
            traceId: 'trace-1',
            generationIds: ['event-uuid-1'],
            timestamp: '2026-06-23T10:00:00Z',
        })
        await jest.advanceTimersByTimeAsync(1)

        expect(mockFetchStoredGenerationSentiments).toHaveBeenLastCalledWith(expect.anything(), expect.anything(), true)

        logic.actions.ensureGenerationSentimentLoaded({
            key: 'event-uuid-2',
            traceId: 'trace-2',
            generationIds: ['event-uuid-2'],
            timestamp: '2026-06-23T10:00:00Z',
        })
        await jest.advanceTimersByTimeAsync(1)

        expect(mockFetchStoredGenerationSentiments).toHaveBeenLastCalledWith(
            expect.anything(),
            expect.anything(),
            false
        )
    })

    // Refresh is what a person clicks while a lookup hangs, so the hung batch can land after the
    // fresh one and put its older answer back in the cell.
    it('ignores a batch that a reset superseded', async () => {
        jest.useFakeTimers()
        let landStalledBatch: (results: Record<string, GenerationSentiment | null>) => void = () => {}
        mockFetchStoredGenerationSentiments.mockReturnValueOnce(
            new Promise((resolve) => {
                landStalledBatch = resolve
            })
        )

        logic.actions.ensureGenerationSentimentLoaded({
            key: 'event-uuid-1',
            traceId: 'trace-1',
            generationIds: ['event-uuid-1'],
            timestamp: '2026-06-23T10:00:00Z',
        })
        await jest.advanceTimersByTimeAsync(1)

        logic.actions.resetGenerationSentiments()
        mockFetchStoredGenerationSentiments.mockResolvedValueOnce({ 'event-uuid-1': sentiment })
        logic.actions.ensureGenerationSentimentLoaded({
            key: 'event-uuid-1',
            traceId: 'trace-1',
            generationIds: ['event-uuid-1'],
            timestamp: '2026-06-23T10:00:00Z',
        })
        await jest.advanceTimersByTimeAsync(1)

        expect(logic.values.getGenerationSentiment('event-uuid-1')).toEqual(sentiment)

        landStalledBatch({})
        await jest.advanceTimersByTimeAsync(1)

        expect(logic.values.getGenerationSentiment('event-uuid-1')).toEqual(sentiment)
    })

    it('returns cached sentiment through the selector', () => {
        logic.actions.loadGenerationSentimentBatchSuccess({ 'event-uuid-1': sentiment }, ['event-uuid-1'])

        expect(logic.values.getGenerationSentiment('event-uuid-1')).toEqual(sentiment)
        expect(logic.values.getGenerationSentiment('event-uuid-2')).toBeUndefined()
    })
})
