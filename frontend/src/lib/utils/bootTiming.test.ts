import type posthogType from 'posthog-js'

import type {
    createSceneRenderedMark as createSceneRenderedMarkType,
    markBootPhase as markBootPhaseType,
} from './bootTiming'

describe('bootTiming', () => {
    // Hash buckets 0 and 26 of 100, so one sits inside the 5% sample and one sits outside it.
    const IN_SAMPLE_ID = 'user-93'
    const OUT_OF_SAMPLE_ID = 'user-0'

    let markBootPhase: typeof markBootPhaseType
    let createSceneRenderedMark: typeof createSceneRenderedMarkType
    let capture: jest.SpyInstance
    let getDistinctId: jest.SpyInstance
    let now: number
    let nowSpy: jest.SpyInstance

    beforeEach(() => {
        // The module keeps once-per-page-load state, so each test loads a fresh copy.
        jest.resetModules()
        now = 0
        nowSpy = jest.spyOn(performance, 'now').mockImplementation(() => now)
        ;({ markBootPhase, createSceneRenderedMark } = require('./bootTiming'))
        const posthog: typeof posthogType = require('posthog-js').default
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        getDistinctId = jest.spyOn(posthog, 'get_distinct_id').mockReturnValue(IN_SAMPLE_ID)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const markAt = (time: number, ...args: Parameters<typeof markBootPhaseType>): void => {
        now = time
        markBootPhase(...args)
    }

    const flushSend = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

    it('sends one event on the first scene render, with times since navigation start', async () => {
        markAt(50.4, 'entry')
        markAt(400, 'app_modules_loaded')
        markAt(620, 'scene_loaded', { scene: 'Insight' })
        // App and scene can commit together, and then the parent's `app_ready` effect runs after the scene's.
        markAt(910.6, 'scene_rendered')
        markAt(911, 'app_ready', { logged_in: true })
        await flushSend()

        markAt(5000, 'scene_loaded', { scene: 'Dashboard' })
        markAt(5100, 'scene_rendered')
        await flushSend()

        expect(capture).toHaveBeenCalledTimes(1)
        expect(capture).toHaveBeenCalledWith(
            'app boot timing',
            expect.objectContaining({
                entry_ms: 50,
                app_modules_loaded_ms: 400,
                scene_loaded_ms: 620,
                app_ready_ms: 911,
                scene_rendered_ms: 911,
                scene: 'Insight',
                logged_in: true,
                page_was_hidden: false,
                sample_rate: 0.05,
            })
        )
    })

    it.each([
        { name: 'marks when the scene commits', fallbackGoneAt: [], expected: 900 },
        { name: 'waits for a lazy content fallback to go', fallbackGoneAt: [1150], expected: 1150 },
        { name: 'waits for the last of two fallbacks', fallbackGoneAt: [1100, 1300], expected: 1300 },
    ])(
        'scene rendered mark $name',
        async ({ fallbackGoneAt, expected }: { fallbackGoneAt: number[]; expected: number }) => {
            markAt(50, 'entry')
            const sceneRendered = createSceneRenderedMark()
            // A child's layout effect runs before its parent's, so a fallback holds the mark before the scene commits.
            const releases = fallbackGoneAt.map(() => sceneRendered.holdUntilContent())
            now = 900
            sceneRendered.sceneCommitted()
            fallbackGoneAt.forEach((time, index) => {
                now = time
                releases[index]()
            })
            await flushSend()

            expect(capture).toHaveBeenCalledTimes(1)
            expect(capture).toHaveBeenCalledWith(
                'app boot timing',
                expect.objectContaining({ scene_rendered_ms: expected })
            )
        }
    )

    it('does not mark a scene that unmounts before lazy content appears', async () => {
        markAt(50, 'entry')
        const sceneRendered = createSceneRenderedMark()
        const release = sceneRendered.holdUntilContent()
        sceneRendered.sceneCommitted()
        release()
        sceneRendered.sceneUncommitted()
        await flushSend()

        expect(capture).not.toHaveBeenCalled()
    })

    it('marks after the lazy content commit completes', async () => {
        markAt(50, 'entry')
        const sceneRendered = createSceneRenderedMark()
        const release = sceneRendered.holdUntilContent()
        sceneRendered.sceneCommitted()
        now = 1100
        release()
        now = 1110
        await flushSend()

        expect(capture).toHaveBeenCalledWith('app boot timing', expect.objectContaining({ scene_rendered_ms: 1110 }))
    })

    it('waits if lazy content starts loading after the scene commit', async () => {
        markAt(50, 'entry')
        const sceneRendered = createSceneRenderedMark()
        sceneRendered.sceneCommitted()
        const release = sceneRendered.holdUntilContent()
        await Promise.resolve()

        expect(capture).not.toHaveBeenCalled()

        now = 1200
        release()
        await flushSend()

        expect(capture).toHaveBeenCalledWith('app boot timing', expect.objectContaining({ scene_rendered_ms: 1200 }))
    })

    it.each([
        { distinctId: IN_SAMPLE_ID, variant: undefined, sampleRate: 0.05 },
        { distinctId: OUT_OF_SAMPLE_ID, variant: undefined, sampleRate: null },
        // An empty ID hashes to bucket 0, so without a guard every such page load would land in the sample.
        { distinctId: '', variant: undefined, sampleRate: null },
        { distinctId: undefined, variant: undefined, sampleRate: null },
        { distinctId: OUT_OF_SAMPLE_ID, variant: 'control', sampleRate: 1 },
        { distinctId: OUT_OF_SAMPLE_ID, variant: 'test', sampleRate: 1 },
    ])(
        'samples on distinct ID $distinctId in variant $variant (sample rate: $sampleRate)',
        async ({ distinctId, variant, sampleRate }) => {
            getDistinctId.mockReturnValue(distinctId)
            markAt(50, 'entry', { deferred_app_context_variant: variant })
            markAt(900, 'scene_rendered')
            await flushSend()

            if (sampleRate === null) {
                expect(capture).not.toHaveBeenCalled()
            } else {
                expect(capture).toHaveBeenCalledWith(
                    'app boot timing',
                    expect.objectContaining({ sample_rate: sampleRate })
                )
            }
        }
    )

    it.each([
        {
            name: 'splits the entry phase with navigation timing',
            navigationEntries: [
                {
                    type: 'navigate',
                    nextHopProtocol: 'h2',
                    domainLookupStart: 2,
                    domainLookupEnd: 30.4,
                    connectStart: 30.4,
                    secureConnectionStart: 80.2,
                    connectEnd: 119.6,
                    requestStart: 120.4,
                    responseStart: 310.6,
                    responseEnd: 352.2,
                },
            ],
            expected: {
                navigation_type: 'navigate',
                next_hop_protocol: 'h2',
                dns_ms: 28,
                connect_ms: 89,
                tls_ms: 39,
                request_start_ms: 120,
                response_start_ms: 311,
                response_end_ms: 352,
            },
        },
        {
            name: 'reports no connection or TLS time on a reused connection',
            navigationEntries: [
                {
                    type: 'reload',
                    nextHopProtocol: 'h2',
                    domainLookupStart: 5,
                    domainLookupEnd: 5,
                    connectStart: 5,
                    secureConnectionStart: 5,
                    connectEnd: 5,
                    requestStart: 6,
                    responseStart: 150,
                    responseEnd: 160,
                },
            ],
            expected: {
                navigation_type: 'reload',
                next_hop_protocol: 'h2',
                dns_ms: 0,
                connect_ms: null,
                tls_ms: null,
                request_start_ms: 6,
                response_start_ms: 150,
                response_end_ms: 160,
            },
        },
        {
            name: 'still sends the event without a navigation entry',
            navigationEntries: [],
            expected: { navigation_type: null },
        },
        {
            name: 'still sends the event without the navigation timing API',
            navigationEntries: undefined,
            expected: { navigation_type: null },
        },
    ])('$name', async ({ navigationEntries, expected }) => {
        // jsdom has no performance.getEntriesByType, so the test adds it and removes it again.
        if (navigationEntries) {
            Object.defineProperty(performance, 'getEntriesByType', {
                configurable: true,
                value: () => navigationEntries,
            })
        }
        try {
            markAt(50, 'entry')
            markAt(900, 'scene_rendered')
            await flushSend()
        } finally {
            Reflect.deleteProperty(performance, 'getEntriesByType')
        }

        const navigationKeys = [
            'navigation_type',
            'next_hop_protocol',
            'dns_ms',
            'connect_ms',
            'tls_ms',
            'request_start_ms',
            'response_start_ms',
            'response_end_ms',
        ]
        const properties = capture.mock.calls[0][1]
        expect(Object.fromEntries(navigationKeys.map((key) => [key, properties[key]]))).toEqual(expected)
    })

    it('reports a page hidden only between two marks', async () => {
        let visibilityState: DocumentVisibilityState = 'visible'
        jest.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibilityState)
        const setVisibility = (state: DocumentVisibilityState): void => {
            visibilityState = state
            document.dispatchEvent(new Event('visibilitychange'))
        }

        markAt(50, 'entry')
        setVisibility('hidden')
        setVisibility('visible')
        markAt(900, 'scene_rendered')
        await flushSend()

        expect(capture).toHaveBeenCalledWith('app boot timing', expect.objectContaining({ page_was_hidden: true }))
    })

    it.each([
        { reason: 'the entry script did not run, as in tests, storybook and the exporter', runEntry: false },
        { reason: 'performance.now is unavailable', runEntry: true, nowThrows: true },
    ])('sends nothing when $reason', async ({ runEntry, nowThrows }) => {
        if (nowThrows) {
            nowSpy.mockImplementation(() => {
                throw new TypeError('performance.now is not a function')
            })
        }
        if (runEntry) {
            markAt(50, 'entry')
        }
        markAt(400, 'app_modules_loaded')
        markAt(700, 'app_ready', { logged_in: true })
        markAt(900, 'scene_rendered')
        await flushSend()

        expect(capture).not.toHaveBeenCalled()
    })
})
