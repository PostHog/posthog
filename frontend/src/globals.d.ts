import posthog from 'posthog-js'

declare global {
    interface Window {
        JS_POSTHOG_API_KEY?: str
        JS_POSTHOG_HOST?: str
        posthog?: posthog
    }
}
