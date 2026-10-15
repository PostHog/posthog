import { NavigationTimeline } from '../navigation-timeline'
import type { PlaybackController } from '../playback-controller'
import { PLAYER_NAVIGATION_KEY, type NavigationSample } from '../protocol'
import type { WindowLabels } from '../window-labels'

describe('NavigationTimeline', () => {
    afterEach(() => {
        delete (window as any)[PLAYER_NAVIGATION_KEY]
    })

    it('records one sample per change of tab or page, labelled the way the footer labels it', () => {
        let onFrame: (sample: number) => void = () => {}
        const controller = {
            activeWindow: { windowId: 1 },
            currentSessionMs: () => 1000,
            onFrame: (listener: (sample: number) => void) => {
                onFrame = listener
            },
        }
        const urls = new Map([
            [1, 'https://ex.com/flags'],
            [2, 'https://ex.com/flags'],
        ])
        const labels = {
            urlAt: (windowId: number) => urls.get(windowId) ?? '',
            numberOf: (windowId: number) => windowId,
        }
        new NavigationTimeline(
            controller as unknown as PlaybackController,
            labels as unknown as WindowLabels,
            new Map([
                [1, 'w-a'],
                [2, 'w-b'],
            ])
        ).start()

        onFrame(0)
        onFrame(1)
        onFrame(2)
        controller.activeWindow = { windowId: 2 }
        onFrame(3)
        urls.set(2, 'https://ex.com/billing')
        onFrame(4)

        expect((window as any)[PLAYER_NAVIGATION_KEY] as NavigationSample[]).toEqual([
            { sample: 0, session_ms: 1000, window_id: 'w-a', window_number: 1, url: 'https://ex.com/flags' },
            { sample: 3, session_ms: 1000, window_id: 'w-b', window_number: 2, url: 'https://ex.com/flags' },
            { sample: 4, session_ms: 1000, window_id: 'w-b', window_number: 2, url: 'https://ex.com/billing' },
        ])
    })
})
