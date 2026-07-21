import type { CaptureOptions, CaptureResult, Properties } from 'posthog-js'
import originalPostHog from 'posthog-js'

// Toolbar shim — lib/posthog-typed is ~200 KB of generated event typings wrapped around a
// small runtime. This mirrors that runtime exactly (capture/captureRaw delegating to the
// posthog-js singleton, everything else proxied through) without the typings.
const enhanced: Record<string, unknown> = {
    capture: (
        event_name: string,
        properties?: Properties | null,
        options?: CaptureOptions
    ): CaptureResult | undefined => originalPostHog.capture(event_name, properties, options),
    captureRaw: (
        event_name: string,
        properties?: Properties | null,
        options?: CaptureOptions
    ): CaptureResult | undefined => originalPostHog.capture(event_name, properties, options),
}

const posthog = new Proxy(enhanced, {
    get(target, prop) {
        if (prop in target) {
            return target[prop as string]
        }
        return (originalPostHog as unknown as Record<string | symbol, unknown>)[prop]
    },
    set(_target, prop, value) {
        ;(originalPostHog as unknown as Record<string | symbol, unknown>)[prop] = value
        return true
    },
}) as unknown as typeof originalPostHog & { captureRaw: typeof originalPostHog.capture }

export default posthog

// Re-export everything else from posthog-js, matching lib/posthog-typed's surface
export * from 'posthog-js'
