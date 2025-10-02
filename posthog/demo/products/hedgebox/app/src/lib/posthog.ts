import posthog from 'posthog-js'

export function initPostHog(): void {
    if (typeof window !== 'undefined') {
        const demoApiToken = process.env.NEXT_PUBLIC_POSTHOG_KEY
        if (!demoApiToken) {
           console.warn('NEXT_PUBLIC_POSTHOG_KEY is not set, skipping PostHog initialization')
           return
        } 
        const localApiHost = process.env.NEXT_PUBLIC_POSTHOG_HOST || 'http://localhost:8010'
        posthog.init(demoApiToken, {
            api_host: localApiHost,
            disable_compression: true,
            capture_pageview: false,
            autocapture: true,
            persistence: 'memory', // Use memory persistence for replay mode to avoid conflicts
            opt_out_useragent_filter: true // We do want capture to work in a bot environment (Playwright)
        })
    }
    (window as any).posthog = posthog
}

export { posthog }
