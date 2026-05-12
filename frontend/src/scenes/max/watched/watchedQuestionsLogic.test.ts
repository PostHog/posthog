import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WatchedQuestion, watchedQuestionsLogic } from './watchedQuestionsLogic'

const teamId = 1

const STUB_QUESTION: WatchedQuestion = {
    id: '11111111-1111-1111-1111-111111111111',
    created_by: { id: 1 },
    conversation_id: '22222222-2222-2222-2222-222222222222',
    human_message_id: '33333333-3333-3333-3333-333333333333',
    visualization_message_id: '44444444-4444-4444-4444-444444444444',
    title: 'Weekly activation',
    question_text: 'What is our weekly activation rate?',
    baseline_summary: 'Baseline activation is 41.3%.',
    baseline_captured_at: '2026-04-02T00:00:00Z',
    cadence: 'weekly',
    status: 'active',
    next_run_at: '2026-04-09T00:00:00Z',
    last_run_at: null,
    repository: '',
    recent_runs: [],
    created_at: '2026-04-02T00:00:00Z',
    updated_at: '2026-04-02T00:00:00Z',
}

describe('watchedQuestionsLogic', () => {
    let logic: ReturnType<typeof watchedQuestionsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/environments/${teamId}/posthog_ai/watched_questions/`]: () => [
                    200,
                    { results: [STUB_QUESTION] },
                ],
            },
            post: {
                [`/api/environments/${teamId}/posthog_ai/watched_questions/${STUB_QUESTION.id}/pause/`]: () => [
                    200,
                    { ...STUB_QUESTION, status: 'paused' },
                ],
                [`/api/environments/${teamId}/posthog_ai/watched_questions/${STUB_QUESTION.id}/resume/`]: () => [
                    200,
                    { ...STUB_QUESTION, status: 'active' },
                ],
                [`/api/environments/${teamId}/posthog_ai/watched_questions/${STUB_QUESTION.id}/run_now/`]: () => [
                    202,
                    {},
                ],
            },
            delete: {
                [`/api/environments/${teamId}/posthog_ai/watched_questions/${STUB_QUESTION.id}/`]: () => [204, {}],
            },
        })
        initKeaTests()
        logic = watchedQuestionsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads watched questions on mount', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.watchedQuestions.map((q) => q.id)).toContain(STUB_QUESTION.id)
    })

    it('togglePanel flips panelOpen', async () => {
        expect(logic.values.panelOpen).toBe(false)
        logic.actions.togglePanel()
        expect(logic.values.panelOpen).toBe(true)
        logic.actions.togglePanel()
        expect(logic.values.panelOpen).toBe(false)
    })

    it('pauseQuestion updates the row in state', async () => {
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.pauseQuestion(STUB_QUESTION.id)
        }).toFinishAllListeners()
        const updated = logic.values.watchedQuestions.find((q) => q.id === STUB_QUESTION.id)
        expect(updated?.status).toBe('paused')
    })
})
