import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SCENARIOS } from './todayFixtures'
import { breakdownDelta, QUESTION_MS, thinkingLines, todayFlowLogic } from './todayFlowLogic'
import { todayLogic } from './todayLogic'

describe('todayFlowLogic', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/signals/reports/': { results: [], count: 0 } } })
        initKeaTests()
    })

    test.each([
        ['14,208', '14,208', 0, 'Baseline'],
        ['14,208', '9,642', 1, '−32%'],
        ['18% retained', '43% retained', 1, '+25 pts'],
        ['100', '100', 2, '±0%'],
    ])('compares %s with %s', (first, current, index, expected) => {
        expect(breakdownDelta(first, current, index)).toBe(expected)
    })

    it('thinks, then shows the board and readies each card on its own schedule', () => {
        jest.useFakeTimers()
        try {
            const today = todayLogic()
            today.mount()
            today.actions.startConversation('How do we grow 2×?', 'growth')
            const conversationId = today.values.conversations[0].id
            const flow = todayFlowLogic({ conversationId, scenarioId: 'growth', question: 'How do we grow 2×?' })
            flow.mount()
            const thinkingMs = thinkingLines(SCENARIOS.growth).reduce((total, line) => total + line.duration, 0)

            jest.advanceTimersByTime(QUESTION_MS)
            expect(flow.values.phase).toBe('thinking')

            jest.advanceTimersByTime(thinkingMs)
            expect(flow.values.phase).toBe('results')
            expect(today.values.conversations[0].status).toBe('answered')
            expect(flow.values.readyEvidenceIds).toEqual(['onboarding-dropoff'])

            jest.advanceTimersByTime(5100)
            expect(flow.values.allReady).toBe(true)
            expect(flow.values.targetReached).toBe(true)

            flow.actions.addToToday('activation-gap')
            expect(today.values.todayItems.map((item) => item.evidenceId)).toEqual(['activation-gap'])
        } finally {
            jest.useRealTimers()
        }
    })
})
