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
                '/api/projects/:team_id/today/pulse_pins/': () => [200, { pins: [] }],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('records which pulse metric was opened and why it was shown', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const logic = todayHighlightsLogic()
        logic.mount()

        logic.actions.pulseMetricOpened(makePulseMetric({ reason: 'dashboard', dashboard_name: 'Growth' }), 2)

        expect(capture).toHaveBeenCalledWith('today pulse metric opened', {
            kind: 'insight',
            reason: 'dashboard',
            position: 2,
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

    it('hides a pulse metric in this project only, fills its place with the next suggestion, and undoes the hide', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const pulse = ['a', 'b', 'c', 'd', 'e'].map((key) => makePulseMetric({ key: `insight:${key}` }))
        highlightResponses = [[200, makeHighlights({ pulse })]]
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const shown = (): string[] => logic.values.pulseTiles.map((metric) => metric.key)

        logic.actions.setHiddenPulseMetrics({ '1:insight:a': true })
        expect(shown()).toEqual(['insight:a', 'insight:b', 'insight:c', 'insight:d'])

        logic.actions.hidePulseMetric(pulse[1], 1)
        expect(shown()).toEqual(['insight:a', 'insight:c', 'insight:d', 'insight:e'])
        expect(capture).toHaveBeenCalledWith('today pulse metric hidden', expect.objectContaining({ position: 1 }))

        logic.actions.unhidePulseMetric(pulse[1], 1)
        expect(shown()).toEqual(['insight:a', 'insight:b', 'insight:c', 'insight:d'])
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

    it('shows the skeleton until there is content, keeps the pulse skeleton while an older result without tiles is replaced, and polls until ready', async () => {
        jest.useFakeTimers()
        const item = makeHighlightItem()
        highlightResponses = [
            [200, makeHighlights({ status: 'computing', generated_at: null })],
            [200, makeHighlights({ status: 'computing', items: [item] })],
            [200, makeHighlights({ items: [item] })],
        ]
        const logic = todayHighlightsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadHighlightsSuccess'])
            .toMatchValues({ highlightsPending: true, pulsePending: true })
        await expectLogic(logic, () => {
            jest.advanceTimersByTime(HIGHLIGHTS_POLL_MS)
        })
            .toDispatchActions(['loadHighlights', 'loadHighlightsSuccess'])
            .toMatchValues({ highlightsPending: false, pulsePending: true, forYouHighlights: [item] })
        await expectLogic(logic, () => {
            jest.advanceTimersByTime(HIGHLIGHTS_POLL_MS)
        })
            .toDispatchActions(['loadHighlights', 'loadHighlightsSuccess'])
            .toMatchValues({ highlights: makeHighlights({ items: [item] }), pulsePending: false })

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

    it('measures the first rendered number and the final result once per home visit', async () => {
        jest.useFakeTimers()
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        highlightResponses = [[200, makeHighlights({ status: 'computing', generated_at: null })]]
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHighlightsSuccess'])
        logic.actions.pulseViewMounted(false)
        logic.actions.pulseViewUpdated()
        await jest.advanceTimersByTimeAsync(400)
        logic.actions.loadHighlightsSuccess(makeHighlights({ status: 'computing', pulse: [makePulseMetric()] }))
        logic.actions.pulseViewUpdated()
        logic.actions.pulseViewUpdated()
        await jest.advanceTimersByTimeAsync(300)
        logic.actions.loadHighlightsSuccess(makeHighlights({ pulse: [makePulseMetric()] }))
        logic.actions.pulseViewUpdated()
        logic.actions.pulseViewUpdated()
        logic.actions.pulseViewUnmounted()

        const events = capture.mock.calls.filter(([event]) => event.startsWith('today pulse'))
        expect(events.map(([event]) => event)).toEqual([
            'today pulse load started',
            'today pulse first number shown',
            'today pulse load finished',
        ])
        expect(events[1][1]).toMatchObject({ duration_ms: 400, first_number_duration_ms: 400, number_count: 1 })
        expect(events[2][1]).toMatchObject({
            load_id: events[0][1]?.load_id,
            duration_ms: 700,
            first_number_duration_ms: 400,
            outcome: 'ready',
            initial_status: 'computing',
            content_at_mount: false,
            was_hidden: false,
        })
    })

    it.each([
        { status: 200, body: makeHighlights(), outcome: 'empty' },
        { status: 200, body: makeHighlights({ status: 'failed' }), outcome: 'failed' },
        { status: 404, body: {}, outcome: 'unavailable' },
        { status: 500, body: {}, outcome: 'request_error' },
    ])('records a terminal $outcome without inventing a first-number time', async ({ status, body, outcome }) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        highlightResponses = [[status, body]]
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.pulseViewMounted(false)
        logic.actions.pulseViewUpdated()

        expect(capture).toHaveBeenCalledWith(
            'today pulse load finished',
            expect.objectContaining({
                outcome,
                first_number_duration_ms: null,
                number_count: 0,
            })
        )
        expect(capture.mock.calls.some(([event]) => event === 'today pulse first number shown')).toBe(false)
        logic.actions.pulseViewUnmounted()
    })

    it('records an already available number without waiting for another request', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        highlightResponses = [[200, makeHighlights({ pulse: [makePulseMetric()] })]]
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const requests = highlightCalls
        logic.actions.pulseViewMounted(false)
        logic.actions.pulseViewUpdated()

        expect(highlightCalls).toBe(requests)
        expect(capture).toHaveBeenCalledWith(
            'today pulse first number shown',
            expect.objectContaining({
                content_at_mount: true,
                initial_status: 'ready',
                number_count: 1,
            })
        )
        logic.actions.pulseViewUnmounted()
    })

    it('records a slow unanswered load and abandonment without stopping the request', async () => {
        jest.useFakeTimers()
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const api = await import('products/today/frontend/generated/api')
        jest.spyOn(api, 'todayHighlightsRetrieve').mockImplementation(() => new Promise(() => {}))
        const logic = todayHighlightsLogic()
        logic.mount()
        logic.actions.pulseViewMounted(false)
        await jest.advanceTimersByTimeAsync(30_000)

        expect(logic.values.highlightsLoading).toBe(true)
        expect(capture).toHaveBeenCalledWith(
            'today pulse load slow',
            expect.objectContaining({
                duration_ms: 30_000,
                request_count: 1,
            })
        )
        logic.actions.pulseViewUnmounted()
        await jest.advanceTimersByTimeAsync(30_000)
        expect(capture.mock.calls.filter(([event]) => event === 'today pulse load slow')).toHaveLength(1)
        expect(capture).toHaveBeenCalledWith(
            'today pulse load finished',
            expect.objectContaining({ outcome: 'abandoned' })
        )
    })

    it('does not measure sample visits', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.pulseViewMounted(true)
        logic.actions.pulseViewUpdated()
        logic.actions.pulseViewUnmounted()

        expect(capture.mock.calls.filter(([event]) => event.startsWith('today pulse load'))).toHaveLength(0)
        expect(capture.mock.calls.some(([event]) => event === 'today pulse first number shown')).toBe(false)
    })

    it.each([false, true])('records document departure once and handles cached restoration: %s', async (persisted) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        highlightResponses = [[200, makeHighlights({ status: 'computing', generated_at: null })]]
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHighlightsSuccess'])
        logic.actions.pulseViewMounted(false)
        const firstLoadId = capture.mock.calls.find(([event]) => event === 'today pulse load started')?.[1]?.load_id

        window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted }))

        expect(capture).toHaveBeenCalledWith(
            'today pulse load finished',
            expect.objectContaining({ load_id: firstLoadId, outcome: 'abandoned' }),
            { transport: 'sendBeacon', send_instantly: true }
        )
        if (persisted) {
            window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))
            logic.actions.loadHighlightsSuccess(makeHighlights({ pulse: [makePulseMetric()] }))
            logic.actions.pulseViewUpdated()
            const restored = capture.mock.calls.find(
                ([event, properties]) => event === 'today pulse load finished' && properties?.outcome === 'ready'
            )
            expect(restored?.[1]?.load_id).not.toBe(firstLoadId)
            expect(restored?.[1]).toMatchObject({ outcome: 'ready', number_count: 1, load_id: expect.any(String) })
        }
        logic.actions.pulseViewUnmounted()
        window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))
        expect(capture.mock.calls.filter(([event]) => event === 'today pulse load started')).toHaveLength(
            persisted ? 2 : 1
        )
        expect(capture.mock.calls.filter(([event]) => event === 'today pulse load finished')).toHaveLength(
            persisted ? 2 : 1
        )
    })

    it('marks a load that spends time in a hidden tab', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        highlightResponses = [[200, makeHighlights({ status: 'computing', generated_at: null })]]
        const logic = todayHighlightsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHighlightsSuccess'])
        logic.actions.pulseViewMounted(false)
        const visibility = jest.spyOn(document, 'visibilityState', 'get')
        visibility.mockReturnValue('hidden')
        document.dispatchEvent(new Event('visibilitychange'))
        visibility.mockReturnValue('visible')
        document.dispatchEvent(new Event('visibilitychange'))
        logic.actions.loadHighlightsSuccess(makeHighlights({ pulse: [makePulseMetric()] }))
        logic.actions.pulseViewUpdated()

        expect(capture).toHaveBeenCalledWith(
            'today pulse load finished',
            expect.objectContaining({
                started_visible: true,
                visible: true,
                was_hidden: true,
            })
        )
        logic.actions.pulseViewUnmounted()
    })
})
