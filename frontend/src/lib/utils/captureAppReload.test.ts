import { APP_RELOAD_EVENT, captureAppReload } from './captureAppReload'

describe('captureAppReload', () => {
    let sendBeacon: jest.Mock
    let capture: jest.Mock

    beforeEach(() => {
        sendBeacon = jest.fn().mockReturnValue(true)
        Object.defineProperty(window.navigator, 'sendBeacon', {
            value: sendBeacon,
            configurable: true,
            writable: true,
        })
        capture = jest.fn()
        window.JS_POSTHOG_API_KEY = 'test-api-key'
        window.JS_POSTHOG_HOST = 'https://us.example.com'
        window.localStorage.clear()
    })

    afterEach(() => {
        delete window.JS_POSTHOG_API_KEY
        delete window.JS_POSTHOG_HOST
        delete window.posthog
    })

    it('captures through posthog-js with a beacon transport, which the reload cannot cancel', () => {
        window.posthog = { capture } as any

        captureAppReload('scene_import_error', new TypeError('Failed to fetch dynamically imported module: /x.js'))

        expect(capture).toHaveBeenCalledWith(
            APP_RELOAD_EVENT,
            {
                reason: 'scene_import_error',
                error_name: 'TypeError',
                error_message: 'Failed to fetch dynamically imported module: /x.js',
            },
            { send_instantly: true, transport: 'sendBeacon' }
        )
        expect(sendBeacon).not.toHaveBeenCalled()
    })

    it('beacons the capture API directly when posthog-js has not loaded yet', () => {
        window.localStorage.setItem('ph_test-api-key_posthog', JSON.stringify({ distinct_id: 'user-42' }))

        captureAppReload('chunk_load_error_boundary', new Error('ChunkLoadError'))

        expect(sendBeacon).toHaveBeenCalledTimes(1)
        const [url, body] = sendBeacon.mock.calls[0]
        expect(url).toBe('https://us.example.com/e/')
        const event = JSON.parse(body)
        expect(event.event).toBe(APP_RELOAD_EVENT)
        expect(event.distinct_id).toBe('user-42')
        expect(event.properties.reason).toBe('chunk_load_error_boundary')
        expect(event.properties.$current_url).toBe(window.location.href)
    })

    it('reports a thrown non-error without throwing itself', () => {
        captureAppReload('chunk_load_error_boundary', 'just a string')

        const event = JSON.parse(sendBeacon.mock.calls[0][1])
        expect(event.properties.error_name).toBe('unknown')
        expect(event.properties.error_message).toBe('just a string')
        // No persisted distinct id, so the synthetic one must not build a person profile
        expect(event.properties.$process_person_profile).toBe(false)
    })

    it('absorbs a throwing posthog-js capture, so the caller still reaches its reload', () => {
        window.posthog = {
            capture: jest.fn(() => {
                throw new Error('SDK capture blew up')
            }),
        } as any

        expect(() => captureAppReload('scene_import_error', new Error('ChunkLoadError'))).not.toThrow()
    })

    it('sends nothing when capture is opted out for the instance', () => {
        delete window.JS_POSTHOG_API_KEY

        captureAppReload('scene_import_error', new Error('nope'))

        expect(sendBeacon).not.toHaveBeenCalled()
    })
})
