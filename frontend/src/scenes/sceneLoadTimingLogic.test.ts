import posthog from 'posthog-js'

import { inFlightRequestsLogic } from 'lib/logic/inFlightRequestsLogic'

import { initKeaTests } from '~/test/init'

import {
    SCENE_LOAD_ABANDONED_EVENT,
    SCENE_LOAD_SETTLED_EVENT,
    SETTLE_WINDOW_MS,
    sceneLoadTimingLogic,
} from './sceneLoadTimingLogic'

jest.mock('posthog-js')

describe('sceneLoadTimingLogic', () => {
    let logic: ReturnType<typeof sceneLoadTimingLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests(false)
        ;(posthog.capture as jest.Mock).mockClear()
        logic = sceneLoadTimingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    const captured = (event: string): Record<string, any>[] =>
        (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)

    const loadScene = (
        sceneId: string,
        searchParams: Record<string, any> = {},
        hashParams: Record<string, any> = {},
        params: Record<string, any> = {}
    ): void => {
        logic.actions.sceneLoadStarted({ sceneId, sceneKey: undefined, params: { params, searchParams, hashParams } })
    }

    const startRequest = (): void => inFlightRequestsLogic.actions.requestStarted()
    const finishRequest = (failed = false): void => inFlightRequestsLogic.actions.requestFinished(failed)

    const loadAndSettle = (sceneId: string, searchParams = {}, hashParams = {}, params = {}): void => {
        loadScene(sceneId, searchParams, hashParams, params)
        startRequest()
        finishRequest()
        jest.advanceTimersByTime(SETTLE_WINDOW_MS)
    }

    it('times the first scene from navigation start to its last response, once the settle window passes', () => {
        jest.advanceTimersByTime(50)
        loadScene('WebAnalytics')
        jest.advanceTimersByTime(100)
        startRequest()
        startRequest()
        jest.advanceTimersByTime(200)
        finishRequest()
        jest.advanceTimersByTime(100)
        finishRequest(true)

        expect(captured(SCENE_LOAD_SETTLED_EVENT)).toHaveLength(0)
        jest.advanceTimersByTime(SETTLE_WINDOW_MS)

        expect(captured(SCENE_LOAD_SETTLED_EVENT)).toEqual([
            {
                scene: 'WebAnalytics',
                trigger: 'page_load',
                duration_ms: 450,
                time_to_first_request_ms: 150,
                request_count: 2,
                failed_request_count: 1,
            },
        ])
        expect(captured(SCENE_LOAD_ABANDONED_EVENT)).toHaveLength(0)
    })

    it('keeps the cycle open across a gap between sequential requests', () => {
        loadScene('WebAnalytics')
        startRequest()
        finishRequest()
        jest.advanceTimersByTime(SETTLE_WINDOW_MS - 100)
        startRequest()
        jest.advanceTimersByTime(SETTLE_WINDOW_MS * 2)

        expect(captured(SCENE_LOAD_SETTLED_EVENT)).toHaveLength(0)

        finishRequest()
        jest.advanceTimersByTime(SETTLE_WINDOW_MS)

        expect(captured(SCENE_LOAD_SETTLED_EVENT)).toEqual([expect.objectContaining({ request_count: 2 })])
    })

    it('reports abandoned when the scene changes with requests in flight', () => {
        loadAndSettle('Home')
        loadScene('WebAnalytics')
        startRequest()
        startRequest()
        finishRequest()
        jest.advanceTimersByTime(300)

        loadScene('FeatureFlags')

        expect(captured(SCENE_LOAD_ABANDONED_EVENT)).toEqual([
            {
                scene: 'WebAnalytics',
                trigger: 'navigation',
                duration_ms: 300,
                request_count: 2,
                failed_request_count: 0,
                requests_in_flight: 1,
            },
        ])
    })

    it('settles rather than abandons when the scene changes inside the settle window', () => {
        loadScene('WebAnalytics')
        startRequest()
        jest.advanceTimersByTime(300)
        finishRequest()
        jest.advanceTimersByTime(100)

        loadScene('FeatureFlags')

        expect(captured(SCENE_LOAD_SETTLED_EVENT)).toEqual([expect.objectContaining({ duration_ms: 300 })])
        expect(captured(SCENE_LOAD_ABANDONED_EVENT)).toHaveLength(0)
    })

    it.each([
        ['another scene', 'FeatureFlags', {}, {}, {}, ['page_load', 'navigation']],
        ['another entity on the same scene', 'Insight', {}, {}, { shortId: 'b' }, ['page_load', 'navigation']],
        ['a search param change', 'Insight', { tab: 'paths' }, {}, { shortId: 'a' }, ['page_load', 'params_change']],
        ['a hash-only change', 'Insight', {}, { panel: 'notebooks' }, { shortId: 'a' }, ['page_load']],
    ])('labels the cycle after %s', (_, nextSceneId, searchParams, hashParams, params, triggers) => {
        loadAndSettle('Insight', {}, {}, { shortId: 'a' })
        loadAndSettle(nextSceneId, searchParams, hashParams, params)

        expect(captured(SCENE_LOAD_SETTLED_EVENT).map((properties) => properties.trigger)).toEqual(triggers)
    })

    it('keeps one cycle when the scene rewrites its own search params before it settles', () => {
        loadAndSettle('Home')
        jest.advanceTimersByTime(1000)
        loadScene('FeatureFlags')
        startRequest()
        loadScene('FeatureFlags', { tab: 'overview' })
        jest.advanceTimersByTime(200)
        finishRequest()
        jest.advanceTimersByTime(SETTLE_WINDOW_MS)

        expect(captured(SCENE_LOAD_ABANDONED_EVENT)).toHaveLength(0)
        expect(captured(SCENE_LOAD_SETTLED_EVENT)[1]).toEqual(
            expect.objectContaining({ scene: 'FeatureFlags', trigger: 'navigation', duration_ms: 200 })
        )
    })

    it('emits nothing for a scene that made no requests', () => {
        loadScene('Settings')
        jest.advanceTimersByTime(SETTLE_WINDOW_MS * 4)
        loadScene('FeatureFlags')

        expect(posthog.capture).not.toHaveBeenCalled()
    })
})
