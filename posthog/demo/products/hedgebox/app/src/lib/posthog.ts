import posthog from 'posthog-js'

export function initPostHog(): void {
    if (typeof window !== 'undefined') {
        const demoApiToken = process.env.NEXT_PUBLIC_POSTHOG_DEMO_TOKEN
        if (!demoApiToken) {
            throw new Error('NEXT_PUBLIC_POSTHOG_DEMO_TOKEN is not set')
        }
        const localApiHost = process.env.NEXT_PUBLIC_POSTHOG_API_HOST
        if (!localApiHost) {
            throw new Error('NEXT_PUBLIC_POSTHOG_API_HOST is not set')
        }
        posthog.init(demoApiToken, {
            api_host: localApiHost,
            disable_compression: true,
            capture_pageview: false,
            autocapture: true,
            persistence: 'memory', // Use memory persistence for replay mode to avoid conflicts
            opt_out_useragent_filter: true // We do want capture to work in a bot environment (Playwright)
        })
    }
    window.posthog = posthog
}

export { posthog }
