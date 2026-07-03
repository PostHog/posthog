import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmGenerationSentimentLazyLoaderLogic } from './llmGenerationSentimentLazyLoaderLogic'
import type { GenerationSentiment } from './sentimentResults'

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
        logic = llmGenerationSentimentLazyLoaderLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
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

    it('clears loading keys after failures', async () => {
        logic.actions.ensureGenerationSentimentLoaded({
            key: 'event-uuid-1',
            traceId: 'trace-1',
            generationIds: ['event-uuid-1'],
        })

        await expectLogic(logic, () => {
            logic.actions.loadGenerationSentimentBatchFailure(['event-uuid-1'])
        }).toMatchValues({
            loadingGenerationKeys: new Set(),
            sentimentByGenerationKey: {
                'event-uuid-1': null,
            },
        })
    })

    it('returns cached sentiment through the selector', () => {
        logic.actions.loadGenerationSentimentBatchSuccess({ 'event-uuid-1': sentiment }, ['event-uuid-1'])

        expect(logic.values.getGenerationSentiment('event-uuid-1')).toEqual(sentiment)
        expect(logic.values.getGenerationSentiment('event-uuid-2')).toBeUndefined()
    })
})
