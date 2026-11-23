import originalPostHog from 'posthog-js'
import type { PostHog as OriginalPostHog } from 'posthog-js'

import type { TypedClient } from '@posthog/sdk/define'

// Type-only, so none of the definitions reach the bundle.
import type * as appEvents from '../../../.ph/us/project-2/app-events'

// The PostHog client the app captures its own events with. `capture` takes only the events defined in
// .ph/us/project-2/app-events, with their declared properties. `captureRaw` takes any event.
// Every other member is posthog-js's own.
export type TypedPostHog = TypedClient<typeof appEvents, OriginalPostHog>

// The same wrapper as `typed()` from @posthog/sdk/define, written here so the app's build doesn't
// need the SDK built: only its types are imported.
function typedPostHog(original: OriginalPostHog): TypedPostHog {
    const capture: OriginalPostHog['capture'] = (event, properties, options) =>
        original.capture(event, properties, options)
    const members: Record<PropertyKey, unknown> = {
        capture,
        captureRaw: capture,
        variant: (key: string) => original.getFeatureFlag(key) ?? undefined,
    }
    return new Proxy(original, {
        get: (target, name, receiver) => (name in members ? members[name] : Reflect.get(target, name, receiver)),
    }) as unknown as TypedPostHog
}

const posthog = typedPostHog(originalPostHog)

export default posthog

export * from 'posthog-js'
