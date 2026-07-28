import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { HogFlowAction, HogFlowWakePlan } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { execHog } from '~/cdp/utils/hog-exec'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'

import { findContinueAction, findNextAction, isEvaluableCondition } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

const DEFAULT_WAIT_DURATION_SECONDS = 10 * 60

// Increments only when the 10-minute polling re-check advances a wait_until_condition that the
// subscription matcher did NOT wake (and not an evaluate-on-entry match). This is the decisive
// signal for removing the poll: while it sits at ~0 across teams for a sustained window, the
// person/event/internal streams cover every wake and polling is provably redundant.
// Labelled by team and flow so a non-zero reading names the workflow still leaning on the poll; a
// series only exists for flows that actually poll-advance, so cardinality tracks incidence.
export const counterHogflowWaitPollOnlyAdvance = new Counter({
    name: 'cdp_hogflow_wait_poll_only_advance',
    help: 'wait_until_condition advanced via the polling re-check, not the subscription matcher — a wake the streams missed.',
    labelNames: ['team_id', 'hog_flow_id'],
})

// Outcome of a wait_until_condition re-check that ran because a person merge re-keyed the parked job
// onto the survivor and woke it (scheduled=now). 'advanced' = the merge made the condition match;
// 'reparked' = it didn't, so waking was wasted churn. A high reparked:advanced ratio means the wake
// is firing on merges that don't satisfy the wait — signal to narrow when the matcher wakes.
export const counterHogflowRekeyWake = new Counter({
    name: 'cdp_hogflow_matcher_rekey_wake_total',
    help: 'wait_until_condition re-checks triggered by a merge re-key wake, by outcome.',
    labelNames: ['outcome'],
})

export class ConditionalBranchHandler implements ActionHandler {
    async execute({
        invocation,
        action,
    }: ActionHandlerOptions<
        Extract<HogFlowAction, { type: 'conditional_branch' | 'wait_until_condition' }>
    >): Promise<ActionHandlerResult> {
        // The subscription matcher sets rekeyWake when it re-keyed this parked wait onto a merge
        // survivor and woke it (scheduled=now). Consume it here (one-shot) and attribute this
        // re-check's outcome to the re-key below, so the wasted-re-park churn from waking is observable.
        const rekeyWoken = action.type === 'wait_until_condition' && invocation.state?.currentAction?.rekeyWake === true
        if (rekeyWoken && invocation.state.currentAction) {
            invocation.state.currentAction.rekeyWake = false
        }

        // The subscription matcher sets eventMatched when an incoming event matched this
        // step's wait condition. Honor it as a forced match and advance immediately,
        // rather than re-evaluating the stored condition against the original event.
        if (action.type === 'wait_until_condition' && invocation.state?.currentAction?.eventMatched === true) {
            invocation.state.currentAction.eventMatched = false
            invocation.state.currentAction.eventMatchedEvent = undefined
            invocation.state.currentAction.eventMatchedEventUuid = undefined
            return {
                nextAction: findNextAction(invocation.hogFlow, action.id, 0),
                result: { eventMatched: true },
            }
        }

        const conditionResult = await checkConditions(
            invocation,
            action.type === 'conditional_branch'
                ? action
                : {
                      ...action,
                      type: 'conditional_branch',
                      config: {
                          // An empty condition compiles to always-true bytecode, which would match on
                          // entry and fire the wait immediately. Only honor a condition with a real
                          // compiled filter; otherwise the wait relies on its events / the timeout.
                          conditions: isEvaluableCondition(action.config.condition) ? [action.config.condition] : [],
                          delay_duration: action.config.max_wait_duration,
                          wake_plan: action.config.wake_plan,
                      },
                  }
        )

        const isWait = action.type === 'wait_until_condition'

        if (conditionResult.scheduledAt) {
            // Record that this wait has re-parked at least once, so a later condition match is
            // attributable to the polling re-check rather than an evaluate-on-entry match.
            if (isWait && invocation.state.currentAction) {
                invocation.state.currentAction.pollReparked = true
            }
            if (rekeyWoken) {
                counterHogflowRekeyWake.labels('reparked').inc()
            }
            return { scheduledAt: conditionResult.scheduledAt, result: { conditionResult } }
        } else if (conditionResult.nextAction) {
            // Poll-only advance: a wait whose condition matched on a re-check (not via the matcher's
            // eventMatched short-circuit above, and not on entry). This is the wake the streams missed.
            if (isWait && invocation.state.currentAction?.pollReparked === true) {
                counterHogflowWaitPollOnlyAdvance
                    .labels({ team_id: invocation.hogFlow.team_id, hog_flow_id: invocation.hogFlow.id })
                    .inc()
            }
            if (rekeyWoken) {
                counterHogflowRekeyWake.labels('advanced').inc()
            }
            return { nextAction: conditionResult.nextAction, result: { conditionResult } }
        }

        return { nextAction: findContinueAction(invocation), result: { conditionResult } }
    }
}

export async function checkConditions(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>
): Promise<{
    scheduledAt?: DateTime
    nextAction?: HogFlowAction
}> {
    // the index is used to find the right edge
    for (const [index, condition] of action.config.conditions.entries()) {
        // TODO(team-workflows): Figure out error handling here - do we throw or just move on to other conditions?
        const filterResults = await filterFunctionInstrumented({
            fn: invocation.hogFlow,
            filters: condition.filters,
            filterGlobals: { ...invocation.filterGlobals, variables: invocation.state.variables },
        })

        if (filterResults.match) {
            return {
                nextAction: findNextAction(invocation.hogFlow, action.id, index),
            }
        }
    }

    if (action.config.delay_duration) {
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp,
            await parkCapSeconds(invocation, action.config.wake_plan)
        )

        if (scheduledAt) {
            return {
                scheduledAt,
            }
        }
    }
    return {}
}

// A wait whose timers reference data that hasn't arrived yet (a person property written by an
// earlier step lands via ingestion, not synchronously) re-checks on this instead of sleeping to the
// deadline. Short because it only has to outlast ingestion lag, and it stops as soon as a timer
// resolves.
const UNRESOLVED_TIMER_RETRY_SECONDS = 5 * 60

/**
 * How long this wait may sleep before its condition is re-checked.
 *
 * `undefined` means "no cap": park straight to the step's own deadline, because every way the
 * condition can become true arrives on a stream the matcher watches. Anything else is a re-check
 * interval, and each case is chosen so no wait ever sleeps longer than it does today:
 *
 *  - a resolvable clock threshold parks to that exact instant (the win: one wake, on time);
 *  - timers present but unresolvable park briefly and retry, since the inputs are still landing;
 *  - a plan we couldn't derive keeps the legacy polling cap, unchanged.
 */
async function parkCapSeconds(
    invocation: CyclotronJobInvocationHogFlow,
    wakePlan: HogFlowWakePlan | null | undefined
): Promise<number | undefined> {
    // No plan means the flow predates wake-plan derivation (or has no condition to derive one
    // from), so we can't prove stream coverage — keep polling it.
    if (!wakePlan || wakePlan.unsupported_reason) {
        return DEFAULT_WAIT_DURATION_SECONDS
    }

    const timers = wakePlan.timers ?? []
    if (timers.length === 0) {
        // Analyzed and clock-free: only a message can satisfy it, and the matcher delivers those.
        return undefined
    }

    const earliest = await earliestFutureTimer(invocation, timers)
    if (earliest === null) {
        return UNRESOLVED_TIMER_RETRY_SECONDS
    }

    // Round up so we never wake a hair early and re-park for the remaining fraction of a second.
    return Math.max(1, Math.ceil(earliest.diff(DateTime.utc()).as('seconds')))
}

/**
 * Evaluate each timer against the invocation's current globals and return the soonest instant still
 * ahead of us, or null when none resolves to one.
 *
 * Earliest rather than latest on purpose: waking early is free (the condition is re-checked and the
 * job re-parks), while waking late means sleeping through the moment the condition flipped.
 */
async function earliestFutureTimer(invocation: CyclotronJobInvocationHogFlow, timers: any[]): Promise<DateTime | null> {
    const globals = { event: invocation.state?.event, person: invocation.person }
    const now = DateTime.utc()
    let earliest: DateTime | null = null

    for (const timer of timers) {
        let instant: DateTime | null = null
        try {
            const result = (await execHog(timer, { globals, timeout: 50 })).execResult?.result
            instant = toDateTime(result)
        } catch {
            // A timer that throws tells us nothing about when to wake; treat it as unresolved so the
            // caller retries rather than trusting a deadline it can't justify.
            instant = null
        }

        if (instant && instant > now && (!earliest || instant < earliest)) {
            earliest = instant
        }
    }

    return earliest
}

/** Coerce a timer's result into a DateTime. HogVM returns HogDateTime for date functions. */
function toDateTime(result: unknown): DateTime | null {
    if (result && typeof result === 'object' && '__hogDateTime__' in result) {
        const dt = (result as unknown as { dt: unknown }).dt
        return typeof dt === 'number' ? DateTime.fromSeconds(dt, { zone: 'utc' }) : null
    }
    if (typeof result === 'number') {
        return DateTime.fromSeconds(result, { zone: 'utc' })
    }
    return null
}
