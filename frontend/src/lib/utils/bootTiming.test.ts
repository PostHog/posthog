import type posthogType from 'posthog-js'

import type { markBootPhase as markBootPhaseType } from './bootTiming'

describe('bootTiming', () => {
    // Hash buckets 0 and 26 of 100, so one sits inside the 5% sample and one sits outside it.
    const IN_SAMPLE_ID = 'user-93'
    const OUT_OF_SAMPLE_ID = 'user-0'

    let markBootPhase: typeof markBootPhaseType
    let capture: jest.SpyInstance
    let getDistinctId: jest.SpyInstance
    let now: number
    let nowSpy: jest.SpyInstance

    beforeEach(() => {
        // The module keeps once-per-page-load state, so each test loads a fresh copy.
        jest.resetModules()
        now = 0
        nowSpy = jest.spyOn(performance, 'now').mockImplementation(() => now)
        markBootPhase = require('./bootTiming').markBootPhase
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
        { distinctId: IN_SAMPLE_ID, sends: true },
        { distinctId: OUT_OF_SAMPLE_ID, sends: false },
        // An empty ID hashes to bucket 0, so without a guard every such page load would land in the sample.
        { distinctId: '', sends: false },
        { distinctId: undefined, sends: false },
    ])('samples on distinct ID $distinctId (sends: $sends)', async ({ distinctId, sends }) => {
        getDistinctId.mockReturnValue(distinctId)
        markAt(50, 'entry')
        markAt(900, 'scene_rendered')
        await flushSend()

        expect(capture).toHaveBeenCalledTimes(sends ? 1 : 0)
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
