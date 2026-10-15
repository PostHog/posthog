import type { PostHog } from 'posthog-js'

// pinned: analytics event and property names. Boot performance insights read them.
const BOOT_TIMING_EVENT = 'app boot timing'

export type BootPhase = 'entry' | 'app_modules_loaded' | 'app_ready' | 'scene_loaded' | 'scene_rendered'

export interface BootContext {
    scene?: string
    logged_in?: boolean
}

const phaseTimes: Partial<Record<BootPhase, number>> = {}
const context: BootContext = {}
let pageWasHidden = false
let sent = false

function getNavigationType(): string | null {
    const navigation = performance.getEntriesByType?.('navigation')[0] as PerformanceNavigationTiming | undefined
    return navigation?.type ?? null
}

function sendBootTiming(posthog: PostHog): void {
    sent = true
    const durations = Object.fromEntries(
        Object.entries(phaseTimes).map(([phase, time]) => [`${phase}_ms`, Math.round(time)])
    )
    posthog.capture(BOOT_TIMING_EVENT, {
        ...durations,
        ...context,
        navigation_type: getNavigationType(),
        page_was_hidden: pageWasHidden,
    })
}

/**
 * Records the first time a full page load reaches a boot phase, as a `performance.mark` and as ms since
 * navigation start. The first scene render sends all phases as one event. Later SPA navigations change nothing.
 */
export function markBootPhase(phase: BootPhase, phaseContext?: BootContext): void {
    // Only the app entry script marks `entry`. Without it, this code runs in tests, storybook or the exporter.
    if (sent || phaseTimes[phase] !== undefined || (phase !== 'entry' && phaseTimes.entry === undefined)) {
        return
    }
    try {
        phaseTimes[phase] = performance.now()
        performance.mark?.(`posthog:boot:${phase}`)
        // A background tab throttles timers and skips rendering, so its boot times are not comparable.
        pageWasHidden ||= document.visibilityState === 'hidden'
    } catch {
        return
    }
    Object.assign(context, phaseContext)
    if (phase === 'scene_rendered') {
        // The entry chunk imports this module, and a static import would pull posthog-js into it.
        // import() also resolves after the current React commit. A parent's layout effect runs after
        // its children's, so an `app_ready` mark from the same commit still gets into the event.
        void import('posthog-js').then(({ default: posthog }) => sendBootTiming(posthog)).catch(() => {})
    }
}
