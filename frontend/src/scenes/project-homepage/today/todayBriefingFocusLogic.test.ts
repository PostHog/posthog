import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MAX_FOCUS_TOPICS, activeFocus, focusSummary, focusTopics } from './todayBriefingFocus'
import { todayBriefingFocusLogic } from './todayBriefingFocusLogic'

describe('todayBriefingFocusLogic', () => {
    let logic: ReturnType<typeof todayBriefingFocusLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/for_you/': { results: [], count: 0 },
                '/api/projects/:team_id/today/briefing/': () => [404, { detail: 'Not found.' }],
            },
        })
        // The saved focus persists in local storage, so each test starts without one.
        window.localStorage.clear()
        initKeaTests()
        logic = todayBriefingFocusLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('saves the draft with an expiry a week out', () => {
        logic.actions.openFocusDialog()
        logic.actions.setDraftTopic('error_tracking', 'more')
        logic.actions.setDraftTopic('surveys', 'less')
        logic.actions.saveFocus()

        const { focus } = logic.values
        expect(focus.topics).toEqual({ error_tracking: 'more', surveys: 'less' })
        expect(Date.parse(focus.until!) - Date.now()).toBeGreaterThan(6 * 24 * 60 * 60 * 1000)
        expect(logic.values.focusDialogOpen).toBe(false)
        expect(logic.values.currentFocusSummary).toEqual('Focused on Error tracking, less surveys')
    })

    it('drops a canceled edit, so the next opening starts from what is saved', () => {
        logic.actions.openFocusDialog()
        logic.actions.setDraftTopic('logs', 'more')
        logic.actions.saveFocus()
        logic.actions.openFocusDialog()
        logic.actions.setDraftTopic('logs', null)
        logic.actions.closeFocusDialog()
        logic.actions.openFocusDialog()

        expect(logic.values.draft.topics).toEqual({ logs: 'more' })
    })

    it('steers one topic from a report and keeps the others', () => {
        logic.actions.openFocusDialog()
        logic.actions.setDraftTopic('logs', 'more')
        logic.actions.setDraftTopic('surveys', 'more')
        logic.actions.setDraftDuration('always')
        logic.actions.saveFocus()
        logic.actions.steerTopic('surveys', 'less')

        expect(logic.values.focus).toEqual({
            topics: { logs: 'more', surveys: 'less' },
            duration: 'always',
            until: null,
        })
    })

    it('stops applying a focus after it expires', () => {
        const focus = { topics: { logs: 'more' as const }, duration: 'week' as const, until: '2026-09-28T08:00:00Z' }

        expect(activeFocus(focus, Date.parse('2026-09-28T07:59:00Z'))).toBe(focus)
        expect(activeFocus(focus, Date.parse('2026-09-28T08:00:00Z')).topics).toEqual({})
    })

    it("offers saved topics first, then the products of the person's reports, without repeats", () => {
        const topics = focusTopics(
            { topics: { surveys: 'less' }, duration: 'week', until: null },
            [{ source_product: 'llm_analytics' }, { source_product: null }],
            [{ source_products: ['error_tracking', 'llm_analytics', 'product_analytics'] }]
        )

        expect(topics.slice(0, 3).map((topic) => topic.key)).toEqual(['surveys', 'llm_analytics', 'error_tracking'])
        expect(new Set(topics.map((topic) => topic.label)).size).toEqual(topics.length)
        expect(topics.length).toBeLessThanOrEqual(MAX_FOCUS_TOPICS)
    })

    it('summarizes a focus that only asks for less', () => {
        expect(focusSummary({ topics: { surveys: 'less', logs: 'less' }, duration: 'week', until: null })).toEqual(
            'Less surveys and logs'
        )
    })
})
