import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { logger } from '~/common/utils/logger'

import { CohortMembershipService } from '../cohort-membership.service'
import { findContinueAction, findNextAction, isEvaluableCondition } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

const DEFAULT_WAIT_DURATION_SECONDS = 10 * 60

// Increments only when the 10-minute polling re-check advances a wait_until_condition that the
// subscription matcher did NOT wake (and not an evaluate-on-entry match). This is the decisive
// signal for removing the poll: while it sits at ~0 across teams for a sustained window, the
// person/event/internal streams cover every wake and polling is provably redundant.
export const counterHogflowWaitPollOnlyAdvance = new Counter({
    name: 'cdp_hogflow_wait_poll_only_advance',
    help: 'wait_until_condition advanced via the polling re-check, not the subscription matcher — a wake the streams missed.',
})

export class ConditionalBranchHandler implements ActionHandler {
    constructor(private cohortMembershipService: CohortMembershipService | null = null) {}

    async execute({
        invocation,
        action,
    }: ActionHandlerOptions<
        Extract<HogFlowAction, { type: 'conditional_branch' | 'wait_until_condition' }>
    >): Promise<ActionHandlerResult> {
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
                      },
                  },
            this.cohortMembershipService
        )

        const isWait = action.type === 'wait_until_condition'

        if (conditionResult.scheduledAt) {
            // Record that this wait has re-parked at least once, so a later condition match is
            // attributable to the polling re-check rather than an evaluate-on-entry match.
            if (isWait && invocation.state.currentAction) {
                invocation.state.currentAction.pollReparked = true
            }
            return { scheduledAt: conditionResult.scheduledAt, result: { conditionResult } }
        } else if (conditionResult.nextAction) {
            // Poll-only advance: a wait whose condition matched on a re-check (not via the matcher's
            // eventMatched short-circuit above, and not on entry). This is the wake the streams missed.
            if (isWait && invocation.state.currentAction?.pollReparked === true) {
                counterHogflowWaitPollOnlyAdvance.inc()
            }
            return { nextAction: conditionResult.nextAction, result: { conditionResult } }
        }

        return { nextAction: findContinueAction(invocation), result: { conditionResult } }
    }
}

export async function checkConditions(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>,
    cohortMembershipService: CohortMembershipService | null = null
): Promise<{
    scheduledAt?: DateTime
    nextAction?: HogFlowAction
}> {
    const cohortEvaluation = await buildCohortEvaluation(invocation, action, cohortMembershipService)

    // the index is used to find the right edge
    for (const [index, condition] of action.config.conditions.entries()) {
        // TODO(team-workflows): Figure out error handling here - do we throw or just move on to other conditions?
        const conditionUsesCohorts = (condition.filters?.cohort_ids?.length ?? 0) > 0
        if (conditionUsesCohorts && !cohortEvaluation.functions) {
            // Membership couldn't be determined — fail this condition closed (no match) rather than
            // guessing, so notInCohort can never wrongly pass. Cohort-free conditions still evaluate.
            continue
        }

        const filterResults = await filterFunctionInstrumented({
            fn: invocation.hogFlow,
            filters: condition.filters,
            filterGlobals: { ...invocation.filterGlobals, variables: invocation.state.variables },
            functions: conditionUsesCohorts ? cohortEvaluation.functions : undefined,
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

/**
 * Pre-fetches realtime cohort membership for every cohort referenced by the action's conditions
 * (one batched lookup per invocation) and turns it into the sync inCohort/notInCohort
 * implementations the compiled filter bytecode calls. Returns no functions when membership can't
 * be determined, so cohort-referencing conditions fail closed.
 */
async function buildCohortEvaluation(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>,
    cohortMembershipService: CohortMembershipService | null
): Promise<{ functions?: Record<string, (...args: any[]) => any> }> {
    const cohortIds = Array.from(
        new Set(action.config.conditions.flatMap((condition) => condition.filters?.cohort_ids ?? []))
    )
    if (cohortIds.length === 0) {
        return {}
    }

    const personId = invocation.filterGlobals.person?.id
    if (!personId) {
        // A person-less event genuinely isn't in any cohort — deterministic, no lookup needed
        return {
            functions: {
                inCohort: () => false,
                notInCohort: () => true,
            },
        }
    }

    if (!cohortMembershipService) {
        logger.error('Cohort conditions configured but no cohort membership service is available', {
            teamId: invocation.hogFlow.team_id,
            hogFlowId: invocation.hogFlow.id,
            actionId: action.id,
        })
        return {}
    }

    try {
        const memberships = await cohortMembershipService.fetchMemberships(
            invocation.hogFlow.team_id,
            personId,
            cohortIds
        )
        return {
            functions: {
                inCohort: (cohortId: unknown) => memberships.get(Number(cohortId)) === true,
                notInCohort: (cohortId: unknown) => memberships.get(Number(cohortId)) !== true,
            },
        }
    } catch {
        // Already logged with context by the service
        return {}
    }
}
