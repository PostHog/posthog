// posthog-js `before_send` filters that drop browser exceptions we never want in error
// tracking. The app instruments its own frontend exceptions (`__capturePostHogExceptions`
// in `loadPostHogJS.tsx`), so anything thrown in the browser — including dev-only tooling —
// otherwise lands in the error-tracking inbox.

// Vite's hot-reload client (`/@vite/client`) throws `WebSocket closed without opened.` when
// its HMR socket dies before it ever connected — a dev-server restart, a network blip, or a
// sandbox port mismatch. It only runs in local dev; production bundles never load
// `@vite/client`, so this filter can only ever drop local-dev churn.
const VITE_HMR_MESSAGE = 'WebSocket closed without opened'
const VITE_CLIENT_MODULE = '@vite/client'
const VITE_HMR_TRANSPORT = 'createWebSocketModuleRunnerTransport'

function isViteDevServerException(exception: { value?: string; stacktrace?: { frames?: any[] } }): boolean {
    if (typeof exception?.value === 'string' && exception.value.includes(VITE_HMR_MESSAGE)) {
        return true
    }
    const frames = exception?.stacktrace?.frames
    if (!Array.isArray(frames)) {
        return false
    }
    return frames.some((frame) => {
        const filename = typeof frame?.filename === 'string' ? frame.filename : ''
        const fn = typeof frame?.function === 'string' ? frame.function : ''
        return filename.includes(VITE_CLIENT_MODULE) || fn === VITE_HMR_TRANSPORT
    })
}

// Drops `$exception` events originating from Vite's dev-only HMR client. Generic over the
// minimal event shape so it can be unit-tested without a full posthog-js event.
export function dropDevServerExceptions<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{
        value?: string
        stacktrace?: { frames?: any[] }
    }>
    if (list.some(isViteDevServerException)) {
        return null
    }
    return event
}
