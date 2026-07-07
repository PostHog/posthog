// The toolbar's bundled posthog-js aborts its own telemetry requests after the SDK's
// request timeout and reports the resulting AbortError as an exception. That's a benign
// network blip on our own analytics, not a broken user flow, so we drop it before capture
// rather than let it pollute error tracking. Lives in its own module (free of the
// posthog.init() side effect in toolbarPosthogJS.ts) so it can be imported and unit tested
// without initializing the SDK.
export function dropTelemetryTimeouts<T extends { event?: string; properties?: Record<string, any> } | null>(
    event: T
): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    const list = (event.properties?.$exception_list ?? []) as Array<{ type?: string; value?: string }>
    if (list.some((ex) => ex?.type === 'AbortError' && ex?.value?.includes('PostHog request timed out'))) {
        return null
    }
    return event
}
