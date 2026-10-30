// pinned: analytics event and property names. Boot performance insights read them.
const BOOT_TIMING_EVENT = 'app boot timing'
const SAMPLE_RATE = 0.05

export type BootPhase =
    | 'entry'
    | 'app_context_loaded'
    | 'app_modules_loaded'
    | 'css_ready'
    | 'app_booted'
    | 'app_first_render'
    | 'app_ready'
    | 'scene_loaded'
    | 'scene_rendered'

export interface BootContext {
    scene?: string
    logged_in?: boolean
    deferred_app_context?: boolean
    deferred_app_context_variant?: string
}

const phaseTimes: Partial<Record<BootPhase, number>> = {}
const context: BootContext = {}
let pageWasHidden = false
let sent = false

function getNavigationProperties(): Record<string, string | number | null> {
    const navigation = performance.getEntriesByType?.('navigation')[0] as PerformanceNavigationTiming | undefined
    if (!navigation) {
        return { navigation_type: null }
    }
    const openedNewConnection = navigation.connectEnd > navigation.connectStart
    const didTlsHandshake = openedNewConnection && navigation.secureConnectionStart > 0
    return {
        navigation_type: navigation.type,
        next_hop_protocol: navigation.nextHopProtocol || null,
        dns_ms: Math.round(navigation.domainLookupEnd - navigation.domainLookupStart),
        connect_ms: openedNewConnection ? Math.round(navigation.connectEnd - navigation.connectStart) : null,
        tls_ms: didTlsHandshake ? Math.round(navigation.connectEnd - navigation.secureConnectionStart) : null,
        request_start_ms: Math.round(navigation.requestStart),
        response_start_ms: Math.round(navigation.responseStart),
        response_end_ms: Math.round(navigation.responseEnd),
    }
}

// A background tab throttles timers and skips rendering, so its boot times are not comparable.
function recordHidden(): void {
    pageWasHidden ||= document.visibilityState === 'hidden'
}

async function sendBootTiming(): Promise<void> {
    // The entry chunk imports this module, and static imports would pull these modules into it.
    // import() also resolves after the current React commit. A parent's layout effect runs after
    // its children's, so an `app_ready` mark from the same commit still gets into the event.
    const [{ default: posthog }, { hashCodeForString }] = await Promise.all([
        import('posthog-js'),
        import('lib/utils/strings'),
    ])
    sent = true
    document.removeEventListener('visibilitychange', recordHidden)

    // Not `$device_id`: posthog-js gives it a new value on each page load of a user bootstrapped with
    // `identity_distinct_id`. The distinct ID changes only at login, so a user stays in or out across page loads.
    const distinctId = posthog.get_distinct_id()
    // An experiment on boot time needs every page load of its users, not the 5% sample.
    const sampleRate = context.deferred_app_context_variant ? 1 : SAMPLE_RATE
    // hashCodeForString returns 0 for an empty string, which would put every such page load in the sample.
    if (!distinctId?.trim() || hashCodeForString(distinctId) % 100 >= sampleRate * 100) {
        return
    }
    const durations = Object.fromEntries(
        Object.entries(phaseTimes).map(([phase, time]) => [`${phase}_ms`, Math.round(time)])
    )
    posthog.capture(BOOT_TIMING_EVENT, {
        ...durations,
        ...context,
        ...getNavigationProperties(),
        page_was_hidden: pageWasHidden,
        sample_rate: sampleRate,
    })
}

/**
 * Records the first time a full page load reaches a boot phase, as a `performance.mark` and as ms since
 * navigation start. The first scene render sends all phases as one event, for a 5% sample of users. Later SPA
 * navigations change nothing.
 */
export function markBootPhase(phase: BootPhase, phaseContext?: BootContext): void {
    // Only the app entry script marks `entry`. Without it, this code runs in tests, storybook or the exporter.
    if (sent || phaseTimes[phase] !== undefined || (phase !== 'entry' && phaseTimes.entry === undefined)) {
        return
    }
    try {
        phaseTimes[phase] = performance.now()
        performance.mark?.(`posthog:boot:${phase}`)
        recordHidden()
        if (phase === 'entry') {
            document.addEventListener('visibilitychange', recordHidden)
        }
    } catch {
        return
    }
    Object.assign(context, phaseContext)
    if (phase === 'scene_rendered') {
        void sendBootTiming().catch(() => {})
    }
}

export interface SceneRenderedMark {
    /** Holds the mark while a Suspense fallback stands in for the scene's lazy content. Returns the release. */
    holdUntilContent: () => () => void
    sceneCommitted: () => void
    sceneUncommitted: () => void
}

/**
 * Marks `scene_rendered` when the scene has committed and no fallback for its lazy content is on screen.
 * Without this, a scene that wraps its content in its own Suspense marks the commit of its spinner.
 */
export function createSceneRenderedMark(): SceneRenderedMark {
    let committed = false
    let holds = 0
    const markIfReady = (): void => {
        if (committed && holds === 0) {
            queueMicrotask(() => {
                if (committed && holds === 0) {
                    markBootPhase('scene_rendered')
                }
            })
        }
    }
    return {
        holdUntilContent: () => {
            holds++
            let released = false
            return () => {
                if (!released) {
                    released = true
                    holds--
                    markIfReady()
                }
            }
        },
        sceneCommitted: () => {
            committed = true
            markIfReady()
        },
        sceneUncommitted: () => {
            committed = false
        },
    }
}
