import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CohortMembershipRepository } from '~/cdp/services/cohorts/cohort-membership-repository'
import { CyclotronJobInvocationHogFlow, HogFunctionFilters } from '~/cdp/types'
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
        // follows to wake it. Re-read before the first evaluation of each wait — including a wait
        // reached later in the same dequeue. Re-checks of a wait that already parked run 10 minutes
        // apart, by when the cache has expired, so they keep the cheaper read.
        if (action.type === 'wait_until_condition' && !invocation.state?.currentAction?.pollReparked) {
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
            this.createMemberCohortIdsLoader(invocation)
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

export async function checkConditions(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>,
    loadMemberCohortIds?: () => Promise<number[]>
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
        // Re-park on the 10-minute cap so the condition is re-checked by polling. The subscription
        // matcher also wakes the job early on a matching signal, but polling is kept as the backstop
        // for now; removing it is a follow-up once the matcher streams are proven in production.
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp,
            DEFAULT_WAIT_DURATION_SECONDS
        )

        if (scheduledAt) {
            return {
                scheduledAt,
            }
        }
    }
    return {}
}
