import posthog from 'posthog-js'

declare global {
    interface Window {
        JS_POSTHOG_API_KEY?: str
        JS_POSTHOG_HOST?: str
        JS_POSTHOG_SELF_CAPTURE?: boolean
        JS_CAPTURE_INTERNAL_METRICS?: boolean
        posthog?: posthog
    }
}
