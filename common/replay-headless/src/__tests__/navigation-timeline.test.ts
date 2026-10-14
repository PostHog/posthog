import { NavigationTimeline } from '../navigation-timeline'
import type { PageUrls } from '../page-urls'
import type { PlaybackController } from '../playback-controller'
import { PLAYER_NAVIGATION_KEY, type NavigationSample } from '../protocol'

describe('NavigationTimeline', () => {
    afterEach(() => {
        delete (window as any)[PLAYER_NAVIGATION_KEY]
    })

    it('records one sample per change of tab or page, without the query string', () => {
        let onFrame: (sample: number) => void = () => {}
        const controller = {
            activeWindow: { windowId: 1 },
            currentSessionMs: () => 1000,
            onFrame: (listener: (sample: number) => void) => {
                onFrame = listener
            },
        }
        const urls = new Map([
            [1, 'https://ex.com/flags?tab=overview'],
            [2, 'https://ex.com/flags'],
        ])
        const pageUrls = { urlOf: (windowId: number) => urls.get(windowId) ?? '' }
        new NavigationTimeline(
            controller as unknown as PlaybackController,
            pageUrls as unknown as PageUrls,
            new Map([
                [1, 'w-a'],
                [2, 'w-b'],
            ])
        ).start()

        onFrame(0)
        onFrame(1)
        urls.set(1, 'https://ex.com/flags')
        onFrame(2)
        controller.activeWindow = { windowId: 2 }
        onFrame(3)
        urls.set(2, 'https://ex.com/billing')
        onFrame(4)

        expect((window as any)[PLAYER_NAVIGATION_KEY] as NavigationSample[]).toEqual([
            { sample: 0, session_ms: 1000, window_id: 'w-a', url: 'https://ex.com/flags' },
            { sample: 3, session_ms: 1000, window_id: 'w-b', url: 'https://ex.com/flags' },
            { sample: 4, session_ms: 1000, window_id: 'w-b', url: 'https://ex.com/billing' },
        ])
    })
})
