/**
 * PostHog Code embedded-app entry.
 *
 * Boots the full PostHog app inside an iframe controlled by a desktop host
 * (PostHog Code). The host serves this entry through a local auth-injecting
 * proxy, so the app sees a same-origin `/api` and never handles credentials.
 *
 * Tracking stays off: we clear JS_POSTHOG_API_KEY before loadPostHogJS runs,
 * which makes posthog-js init with a fake token and opt out (same pattern as
 * the exporter and render-query entries).
 */

declare global {
    interface Window {
        __POSTHOG_EMBED__?: boolean
        __POSTHOG_EMBED_THEME__?: 'light' | 'dark'
    }
}

window.JS_POSTHOG_API_KEY = undefined
window.__POSTHOG_EMBED__ = true

// The host can seed the initial theme via query param (survives until the
// bridge is up and can receive live setTheme messages) or a pre-set global.
const themeParam = new URLSearchParams(window.location.search).get('__posthog_embed_theme')
if (themeParam === 'light' || themeParam === 'dark') {
    window.__POSTHOG_EMBED_THEME__ = themeParam
}

// Dynamic imports only: static imports would hoist above the global setup.
void import('../index').then(() => import('./bridge')).then(({ initEmbedBridge }) => initEmbedBridge())

export {}
