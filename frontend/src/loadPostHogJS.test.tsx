import posthog from 'posthog-js'

import { loadPostHogJS } from './loadPostHogJS'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: {
        init: jest.fn(),
        get_session_id: jest.fn(() => 'session-id'),
        onFeatureFlags: jest.fn(),
    },
}))
jest.mock('posthog-js/lib/src/extensions/sampling', () => ({
    sampleOnProperty: jest.fn(() => false),
}))

describe('loadPostHogJS', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        window.JS_POSTHOG_API_KEY = 'primary-key'
        window.JS_POSTHOG_HOST = 'https://ingest.example.com'
    })

    afterEach(() => {
        delete window.JS_POSTHOG_API_KEY
        delete window.JS_POSTHOG_HOST
        delete window.JS_POSTHOG_HOBBY_EXPERIENCE_API_KEY
    })

    it('leaves replay and exceptions on the primary instance without a hobby experience key', () => {
        loadPostHogJS()

        expect(posthog.init).toHaveBeenCalledTimes(1)
        const config = (posthog.init as jest.Mock).mock.calls[0][1]
        expect(config.disable_session_recording).toBe(false)
        expect(config.capture_exceptions).toBeUndefined()
    })

    it('pins replay and exceptions off on the primary instance and initializes the hobby experience instance', () => {
        window.JS_POSTHOG_HOBBY_EXPERIENCE_API_KEY = 'hobby-key'

        loadPostHogJS()

        expect(posthog.init).toHaveBeenCalledTimes(2)
        const [primaryKey, primaryConfig] = (posthog.init as jest.Mock).mock.calls[0]
        expect(primaryKey).toBe('primary-key')
        expect(primaryConfig.disable_session_recording).toBe(true)
        expect(primaryConfig.capture_exceptions).toBe(false)

        const [hobbyKey, hobbyConfig, hobbyName] = (posthog.init as jest.Mock).mock.calls[1]
        expect(hobbyKey).toBe('hobby-key')
        expect(hobbyName).toBe('posthog_hobby_experience')
        expect(hobbyConfig.capture_exceptions).toBe(true)
        expect(hobbyConfig.autocapture).toBe(false)
        expect(hobbyConfig.capture_pageview).toBe(false)
        expect(hobbyConfig.advanced_disable_feature_flags).toBe(true)
        expect(hobbyConfig.session_recording.maskAllInputs).toBe(true)
    })
})
