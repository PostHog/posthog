import { Counter } from 'prom-client'

import { HogFlow } from '~/cdp/schema/hogflow'

import { ConversionWatcherRow, CyclotronJobInvocationHogFlow, PinnedConversionGoal } from '../../types'
import { durationSeconds } from './duration'
import { hasEventOrActionTarget } from './hogflow-utils'

// A goal is configured if either detection path has something to evaluate. Gates the watcher: a
// workflow with no goal has nothing to measure, so it writes no rows.
function pinConversionGoal(hogFlow: HogFlow): PinnedConversionGoal | null {
    const properties = hogFlow.conversion?.filters?.length ? hogFlow.conversion.bytecode : undefined
    // Drop entries that target neither events nor actions: those compile to always-true bytecode and
    // would count a conversion on the first event of any kind. Same guard the wait_until and conversion
    // evaluators apply — pin it here too so the watcher path agrees with them.
    const events = (hogFlow.conversion?.events ?? [])
        .filter(hasEventOrActionTarget)
        .map((eventConfig) => eventConfig.filters?.bytecode)
        .filter((bytecode): bytecode is any[] => Array.isArray(bytecode) && bytecode.length > 0)

    if (!properties?.length && !events.length) {
        return null
    }
    return {
        ...(properties?.length ? { properties } : {}),
        ...(events.length ? { events } : {}),
    }
}

// The watcher outlives the run, which is the whole point: once the run finishes its cyclotron job is
// gone, and a conversion landing after that has nothing left to match against. See the
// conversion_watchers migration.
//
// A run is enrolling iff it has no `currentAction` yet: every dispatch path (events, warehouse,
// webhooks, batch children, reruns) creates the invocation without one, and `ensureCurrentAction`
// fills it in on the first execution. `ON CONFLICT (id) DO NOTHING` on the insert makes a retry after
// a crash idempotent, since the id is derived from the run.
export function buildConversionWatcher(invocation: CyclotronJobInvocationHogFlow): ConversionWatcherRow | null {
    if (invocation.state.currentAction) {
        return null
    }
    const goal = pinConversionGoal(invocation.hogFlow)
    if (!goal) {
        return null
    }
    const distinctId = invocation.state.event?.distinct_id || null
    const personId = invocation.person?.id ?? invocation.state.personId ?? null
    // Without either key the matcher can never look this watcher up, so the row would be dead weight.
    if (!distinctId && !personId) {
        return null
    }
    return {
        id: invocation.id,
        team_id: invocation.hogFlow.team_id,
        function_id: invocation.hogFlow.id,
        run_id: invocation.id,
        parent_run_id: invocation.parentRunId ?? null,
        distinct_id: distinctId,
        person_id: personId,
        flow_version: invocation.state.flowVersion ?? null,
        goal,
        expires_at: new Date(Date.now() + conversionWindowMinutes(invocation.hogFlow) * 60_000),
    }
}

// What a workflow measures when it sets no explicit window. This answers "how long after entering the
// workflow does a conversion still count", so it is a product choice rather than a storage one. A
// workflow whose own steps run past this can never measure the back half of its own runs.
export const DEFAULT_CONVERSION_WINDOW_MINUTES = 90 * 24 * 60

// The ceiling on a window given as a duration string. It exists only to bound the table: a row that
// never expires is a row the sweep can never reclaim.
export const MAX_CONVERSION_WINDOW_MINUTES = 365 * 24 * 60

// The ceiling on the deprecated integer field. It stays where it is because a bare number cannot be
// trusted to be minutes: the values above it are second counts in a field that takes minutes, so
// `604800` means seven days rather than 420. Honoring those to the full ceiling would credit a
// week-long sequence with a conversion nearly a year later. A duration string cannot be misread, so
// only that form earns the higher ceiling.
export const MAX_LEGACY_WINDOW_MINUTES = 90 * 24 * 60

// Substituting our window for the configured one changes what the workflow's conversion rate measures,
// so it must not be silent: a clamped run reports over the cap, not over the window it asked for.
const counterConversionWindowClamped = new Counter({
    name: 'cdp_conversion_window_clamped',
    help: 'Runs enrolled with a conversion window shortened to the cap because the workflow configured a longer one. Each one measures its conversion rate over a shorter period than the workflow asked for.',
})

// A window we cannot parse is another silent substitution of the measured period, so it gets the same
// treatment as the clamp above: a counter, not a quiet fallback. It reads zero while the API and worker
// share one ASCII grammar, so a non-zero value flags a row that reached storage past validation.
const counterConversionWindowInvalid = new Counter({
    name: 'cdp_conversion_window_invalid',
    help: 'Runs whose stored conversion window string could not be parsed, so the run fell back to the default or legacy window instead of the one the workflow configured.',
})

function conversionWindowMinutes(hogFlow: HogFlow): number {
    const window = hogFlow.conversion?.window
    if (window) {
        const seconds = durationSeconds(window)
        if (seconds !== null && seconds > 0) {
            return clampWindow(seconds / 60, MAX_CONVERSION_WINDOW_MINUTES)
        }
        // A present window that will not parse means a write reached the row past the API's validation
        // (the two share one ASCII grammar), such as a direct database write. Record the substitution,
        // then fall back: measuring over the fallback window beats measuring over a window nobody can read.
        counterConversionWindowInvalid.inc()
    }
    const legacyMinutes = hogFlow.conversion?.window_minutes
    if (!legacyMinutes || legacyMinutes <= 0) {
        return DEFAULT_CONVERSION_WINDOW_MINUTES
    }
    return clampWindow(legacyMinutes, MAX_LEGACY_WINDOW_MINUTES)
}

function clampWindow(minutes: number, ceiling: number): number {
    if (minutes > ceiling) {
        counterConversionWindowClamped.inc()
        return ceiling
    }
    return minutes
}
