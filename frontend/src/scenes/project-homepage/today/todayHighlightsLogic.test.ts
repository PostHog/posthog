import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HIGHLIGHTS_POLL_MS, todayHighlightsLogic } from './todayHighlightsLogic'
import { makeHighlightItem, makeHighlights } from './todayTestFixtures'

describe('todayHighlightsLogic', () => {
    let highlightResponses: [number, any][]
    let highlightCalls: number

    beforeEach(() => {
        highlightResponses = [[200, makeHighlights()]]
        highlightCalls = 0
        useMocks({
            get: {
                '/api/projects/:team_id/today/highlights/': () => {
                    highlightCalls += 1
                    return highlightResponses.length > 1 ? highlightResponses.shift()! : highlightResponses[0]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        { status: 404, failed: false },
        { status: 500, failed: true },
    ])('reads a $status from highlights as failed: $failed', async ({ status, failed }) => {
        highlightResponses = [[status, { detail: 'Error' }]]
        const logic = todayHighlightsLogic()
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ highlights: null, highlightsFailed: failed, highlightsPending: false })
    })

    it('shows the skeleton until there is content, keeps the last ready content while new highlights compute, and polls until they are ready', async () => {
        jest.useFakeTimers()
        const item = makeHighlightItem()
        highlightResponses = [
            [200, makeHighlights({ status: 'computing', generated_at: null })],
            [200, makeHighlights({ status: 'computing', items: [item] })],
            [200, makeHighlights({ items: [item] })],
        ]
        const logic = todayHighlightsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadHighlightsSuccess']).toMatchValues({ highlightsPending: true })
        await expectLogic(logic, () => {
            jest.advanceTimersByTime(HIGHLIGHTS_POLL_MS)
        })
            .toDispatchActions(['loadHighlights', 'loadHighlightsSuccess'])
            .toMatchValues({ highlightsPending: false, forYouHighlights: [item] })
        await expectLogic(logic, () => {
            jest.advanceTimersByTime(HIGHLIGHTS_POLL_MS)
        })
            .toDispatchActions(['loadHighlights', 'loadHighlightsSuccess'])
            .toMatchValues({ highlights: makeHighlights({ items: [item] }) })

        await jest.advanceTimersByTimeAsync(HIGHLIGHTS_POLL_MS * 3)
        expect(highlightCalls).toBe(3)
    })

    it('keeps a highlight hidden in another project visible here, and forgets earlier days', async () => {
        const item = makeHighlightItem()
        highlightResponses = [[200, makeHighlights({ items: [item] })]]
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const today = makeHighlights().day
        logic.actions.setHiddenHighlights({ '1:alert:a': today, '997:old': '2020-01-01' })

        expect(logic.values.forYouHighlights.map((highlight) => highlight.key)).toEqual(['alert:a'])

        logic.actions.hideHighlight(item, 0)
        expect(logic.values.hiddenHighlights).toEqual({ '1:alert:a': today, '997:alert:a': today })
        expect(logic.values.doneHighlightKeys).toEqual(['alert:a'])
    })
})
