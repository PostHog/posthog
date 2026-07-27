import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { evaluationsList } from '../generated/api'
import { sentimentEvaluationAvailabilityLogic } from '../sentimentEvaluationAvailabilityLogic'
import { fetchSentimentGenerationsPage } from '../sentimentQueries'
import type { SentimentGeneration } from '../sentimentQueries'
import { aiObservabilitySentimentLogic } from './aiObservabilitySentimentLogic'

jest.mock('../generated/api', () => ({
    evaluationsList: jest.fn(),
}))

jest.mock('../sentimentQueries', () => ({
    GENERATIONS_PAGE_SIZE: 200,
    fetchSentimentGenerationsPage: jest.fn(),
}))

const mockEvaluationsList = evaluationsList as jest.MockedFunction<typeof evaluationsList>
const mockFetchSentimentGenerationsPage = fetchSentimentGenerationsPage as jest.MockedFunction<
    typeof fetchSentimentGenerationsPage
>

const generationWithSentiment: SentimentGeneration = {
    uuid: 'generation-1',
    traceId: 'trace-1',
    generationIds: ['generation-1'],
    aiInput: [{ role: 'user', content: 'I love this' }],
    model: 'gpt-5-mini',
    distinctId: 'distinct-1',
    timestamp: '2026-06-23T00:00:00Z',
    createdAt: '2026-06-23T00:00:00Z',
    sentiment: {
        label: 'positive',
        score: 0.9,
        scores: { positive: 0.9, neutral: 0.08, negative: 0.02 },
        messages: {
            '0': {
                label: 'positive',
                score: 0.9,
                scores: { positive: 0.9, neutral: 0.08, negative: 0.02 },
            },
        },
        message_count: 1,
    },
}

describe('aiObservabilitySentimentLogic', () => {
    let logic: ReturnType<typeof aiObservabilitySentimentLogic.build> | null
    let availabilityLogic: ReturnType<typeof sentimentEvaluationAvailabilityLogic.build> | null

    beforeEach(() => {
        initKeaTests()
        mockEvaluationsList.mockResolvedValue({ count: 0, results: [] })
        mockFetchSentimentGenerationsPage.mockResolvedValue({ generations: [], rawCount: 0 })
        logic = null
        availabilityLogic = null
    })

    function mountLogics(): void {
        availabilityLogic = sentimentEvaluationAvailabilityLogic()
        availabilityLogic.mount()

        logic = aiObservabilitySentimentLogic()
        logic.mount()
    }

    afterEach(() => {
        logic?.unmount()
        availabilityLogic?.unmount()
        jest.clearAllMocks()
    })

    it('loads stored sentiment rows even without a configured sentiment evaluation', async () => {
        mockFetchSentimentGenerationsPage.mockResolvedValue({
            generations: [generationWithSentiment],
            rawCount: 1,
        })
        mountLogics()

        await expectLogic(logic!, () => {
            logic!.actions.activate()
        }).toFinishAllListeners()

        expect(mockFetchSentimentGenerationsPage).toHaveBeenCalled()
        expect(logic!.values.generations).toEqual([generationWithSentiment])
        expect(logic!.values.showSentimentEvaluationOnboarding).toBe(false)
    })

    it('shows onboarding only when no configured eval and no stored sentiment rows match', async () => {
        mountLogics()

        await expectLogic(logic!, () => {
            logic!.actions.activate()
        }).toFinishAllListeners()

        expect(logic!.values.hasSentimentEvaluations).toBe(false)
        expect(logic!.values.generations).toEqual([])
        expect(logic!.values.showSentimentEvaluationOnboarding).toBe(true)
    })

    it('does not show onboarding when a sentiment evaluation is configured', async () => {
        mockEvaluationsList.mockResolvedValue({
            results: [{ id: 'sentiment-eval', evaluation_type: 'sentiment' }],
        } as Awaited<ReturnType<typeof evaluationsList>>)
        mountLogics()

        await expectLogic(logic!, () => {
            logic!.actions.activate()
        }).toFinishAllListeners()

        expect(logic!.values.hasSentimentEvaluations).toBe(true)
        expect(logic!.values.generations).toEqual([])
        expect(logic!.values.showSentimentEvaluationOnboarding).toBe(false)
    })
})
