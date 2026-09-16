import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CohortMembershipRepository } from '~/cdp/services/cohorts/cohort-membership-repository'
import { CyclotronJobInvocationHogFlow, HogFunctionFilters } from '~/cdp/types'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'

import { findContinueAction, findNextAction, isEvaluableCondition } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

// A parked conditional_branch has no matcher coverage: every parked-job lookup in the subscription
// matcher is scoped to wait_until_condition, so this re-check is the only thing that advances a
// delayed branch.
const BRANCH_RECHECK_SECONDS = 10 * 60
// A wait parks for its whole max_wait_duration: the subscription matcher wakes it when a matching
// event, person update or internal event arrives, so nothing has to re-check it on a timer.
//
// Increments when a wait's condition only matched once that ceiling arrived. The condition was
// therefore true earlier and no stream woke the run, so this counts wakes the matcher lost. A
// condition turning true in the same second as the ceiling is a coincidence, so a sustained
// non-zero reading names a workflow whose wakes are going missing.
export const counterHogflowWaitAdvancedAtMaxWait = new Counter({
    name: 'cdp_hogflow_wait_advanced_at_max_wait',
    help: 'wait_until_condition that only matched once max_wait_duration elapsed — a wake the streams missed.',
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
    constructor(private cohortMembershipRepository: CohortMembershipRepository) {}

    async execute({
        invocation,
        action,
        result,
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

        // Same for a first-mapping anchor fill: a matcher wake that also carries no eventMatched.
        const anchorWoken =
            action.type === 'wait_until_condition' && invocation.state?.currentAction?.anchorWake === true
        if (anchorWoken && invocation.state.currentAction) {
            invocation.state.currentAction.anchorWake = false
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

        // The person the worker read at dequeue can predate a write this wait is waiting for, and a
        // wait that parks on that read is stuck: the write already happened, so no person message
        // follows to wake it. Re-read before every evaluation of a wait: on entry, and on each
        // matcher wake, where the person the wake refers to is the point of the re-check.
        if (action.type === 'wait_until_condition') {
            const refreshed = await invocation.refreshPerson?.()
            // A refresh that finds no person keeps the dequeue's read. The refresh exists to make a
            // just-written property visible, not to drop a person: a lookup that comes back empty
            // (replica lag, a transient miss) would otherwise evaluate the condition against nothing.
            if (refreshed?.person) {
                invocation.person = refreshed.person
                invocation.filterGlobals = refreshed.filterGlobals
                // The result carries a shallow clone, so rebinding only `invocation` would leave it
                // pointing at the pre-refresh globals for anything that reads it later.
                result.invocation.person = refreshed.person
                result.invocation.filterGlobals = refreshed.filterGlobals
            }
        }

        const conditionalAction: Extract<HogFlowAction, { type: 'conditional_branch' }> =
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
                      },
                  }

        const conditionResult = await checkConditions(
            invocation,
            conditionalAction,
            this.createMemberCohortIdsLoader(invocation),
            action.type === 'wait_until_condition' ? null : BRANCH_RECHECK_SECONDS
        )

        const isWait = action.type === 'wait_until_condition'

        if (conditionResult.scheduledAt) {
            if (rekeyWoken) {
                counterHogflowRekeyWake.labels('reparked').inc()
            }
            return { scheduledAt: conditionResult.scheduledAt, result: { conditionResult } }
        } else if (conditionResult.nextAction) {
            if (isWait && matchedAtMaxWait(invocation, action)) {
                counterHogflowWaitAdvancedAtMaxWait
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

    /**
     * Memoized so one lookup covers every cohort condition in the action. Person-less
     * invocations (warehouse rows, account audiences) are non-members of everything.
     */
    private createMemberCohortIdsLoader(invocation: CyclotronJobInvocationHogFlow): () => Promise<number[]> {
        let loaded: Promise<number[]> | undefined
        return () => {
            if (!loaded) {
                const personUuid = invocation.person?.id ?? invocation.state.personId
                loaded = personUuid
                    ? this.cohortMembershipRepository.getMemberCohortIds(invocation.hogFlow.team_id, personUuid)
                    : Promise.resolve([])
            }
            return loaded
        }
    }
}

// Operation.CALL_GLOBAL from @posthog/hogvm, which is a const enum and can't be imported
// under isolatedModules
const CALL_GLOBAL = 2

// Scans the compiled bytecode so expression-authored inCohort(...) calls count too. Matches the
// call encoding [CALL_GLOBAL, name, argCount] rather than the bare name: string constants and
// property chains put their text in the same flat array, and a stray match here would couple an
// unrelated condition's run to the behavioral cohorts DB.
function conditionReferencesCohorts(condition: { filters?: unknown }): boolean {
    const bytecode = (condition.filters as HogFunctionFilters | null | undefined)?.bytecode
    if (!Array.isArray(bytecode)) {
        return false
    }
    return bytecode.some(
        (op, index) =>
            (op === 'inCohort' || op === 'notInCohort') &&
            bytecode[index - 1] === CALL_GLOBAL &&
            typeof bytecode[index + 1] === 'number'
    )
}

// True when this wait is being evaluated at or past its max_wait_duration. calculatedScheduledAt
// returns null once that instant has passed, which is the same test the timeout path uses.
function matchedAtMaxWait(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' | 'wait_until_condition' }>
): boolean {
    const startedAtTimestamp = invocation.state.currentAction?.startedAtTimestamp
    const maxWait = action.type === 'wait_until_condition' ? action.config.max_wait_duration : undefined
    if (!startedAtTimestamp || !maxWait) {
        return false
    }
    try {
        return calculatedScheduledAt(maxWait, startedAtTimestamp) === null
    } catch {
        // An unreadable duration is the timeout path's problem, not this counter's.
        return false
    }
}

export async function checkConditions(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>,
    loadMemberCohortIds?: () => Promise<number[]>,
    // A wait is normalised into a conditional_branch before it gets here, so the caller decides which
    // cap applies; the type on `action` can no longer tell the two apart.
    // null parks for the caller's full duration. Only a conditional_branch needs a re-check, so only
    // it passes a number; `undefined` still takes the default, which keeps direct callers correct.
    recheckSeconds: number | null = BRANCH_RECHECK_SECONDS
): Promise<{
    scheduledAt?: DateTime
    nextAction?: HogFlowAction
}> {
    // the index is used to find the right edge
    for (const [index, condition] of action.config.conditions.entries()) {
        // Loaded only when evaluation actually reaches a cohort condition, so a run whose earlier
        // condition matches never touches the behavioral cohorts DB. A lookup failure throws here
        // on purpose (following the action's on_error) instead of guessing non-membership; the
        // inCohort/notInCohort STL functions read the resulting cohort_ids global.
        const cohortGlobals =
            loadMemberCohortIds && conditionReferencesCohorts(condition)
                ? { cohort_ids: await loadMemberCohortIds() }
                : {}

        // TODO(team-workflows): Figure out error handling here - do we throw or just move on to other conditions?
        const filterResults = await filterFunctionInstrumented({
            fn: invocation.hogFlow,
            filters: condition.filters,
            filterGlobals: {
                ...invocation.filterGlobals,
                variables: invocation.state.variables,
                ...cohortGlobals,
            },
        })

        if (filterResults.match) {
            return {
                nextAction: findNextAction(invocation.hogFlow, action.id, index),
            }
        }
    }

    if (action.config.delay_duration) {
        // Re-park on the cap for this step type. A wake arriving between this evaluation and the job
        // being persisted finds no available row and is never replayed, so neither step type can rely
        // on the matcher alone.
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp,
            recheckSeconds ?? undefined
        )

        if (scheduledAt) {
            return {
                scheduledAt,
            }
        }
    }
    return {}
}
