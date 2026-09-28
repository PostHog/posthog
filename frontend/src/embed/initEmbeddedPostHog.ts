import posthog from 'posthog-js'

import type { EmbedHost } from './embedTypes'

/**
 * Starts the web app's own posthog-js instance without touching the host's. The host already records
 * the session and its own pageviews, so this instance only serves the web app's feature flags and the
 * events its code captures. It does not assign `window.posthog`, which the host may own.
 */
export function initEmbeddedPostHog(analytics: EmbedHost['analytics']): void {
    if (!analytics) {
        posthog.init('fake_token', {
            autocapture: false,
            advanced_disable_flags: true,
            opt_out_capturing_by_default: true,
            disable_session_recording: true,
            loaded: (instance) => instance.opt_out_capturing(),
        })
        return
    }
    posthog.init(analytics.apiKey, {
        api_host: analytics.apiHost,
        persistence_name: 'ph_embedded_app',
        autocapture: false,
        capture_pageview: false,
        capture_pageleave: false,
        disable_session_recording: true,
        person_profiles: 'always',
        __preview_disable_xhr_credentials: true,
    })
}
