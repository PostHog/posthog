import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HIGHLIGHTS_POLL_MS, todayHighlightsLogic } from './todayHighlightsLogic'
import { makeHighlightItem, makeHighlights, makePulseMetric } from './todayTestFixtures'

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
        jest.restoreAllMocks()
    })

    it('records which pulse metric was opened, why it was shown and the ranking variant', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        jest.spyOn(posthog, 'getFeatureFlag').mockReturnValue('frecency')
        const logic = todayHighlightsLogic()
        logic.mount()

        logic.actions.pulseMetricOpened(makePulseMetric({ reason: 'dashboard', dashboard_name: 'Growth' }), 2)

        expect(capture).toHaveBeenCalledWith('today pulse metric opened', {
            kind: 'insight',
            reason: 'dashboard',
            position: 2,
            pulse_ranking: 'frecency',
        })
    })

    it('records a pulse preview once per metric', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const logic = todayHighlightsLogic()
        logic.mount()

        logic.actions.pulseMetricPreviewed(makePulseMetric(), 0)
        logic.actions.pulseMetricPreviewed(makePulseMetric(), 0)
        logic.actions.pulseMetricPreviewed(makePulseMetric({ key: 'signup_event', reason: 'key_metric' }), 1)

        expect(capture.mock.calls.filter(([event]) => event === 'today pulse metric previewed')).toEqual([
            ['today pulse metric previewed', expect.objectContaining({ kind: 'insight', position: 0 })],
            ['today pulse metric previewed', expect.objectContaining({ kind: 'key_metric', position: 1 })],
        ])
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
