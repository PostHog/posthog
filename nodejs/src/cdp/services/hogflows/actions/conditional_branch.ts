import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/schema/hogflow'

import { findContinueAction, findNextAction, isEvaluableCondition } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

// Plain conditional_branch re-checks are not woken by the subscription matcher, so they keep the
// original tight poll cadence.
const CONDITIONAL_BRANCH_POLL_SECONDS = 10 * 60

// wait_until_condition steps ARE woken in real time by the subscription matcher
// (cdp-hogflow-subscription-matcher) the moment an incoming event matches their `events` or their
// person-property `condition`, so this periodic re-check is no longer the primary wake path — it is
// a safety backstop. It still matters for:
//   - group-property conditions, which the matcher cannot wake on: it finds parked jobs by the
//     waiting person's distinct_id/person_id, but a `$groupidentify` that changes a group property
//     is not tied to that person, so only this re-check (which reloads current group props) sees it
//   - matcher downtime / missed events on the live event stream
//   - firing the max_wait_duration timeout (calculatedScheduledAt clamps the wake to the deadline,
//     so a wait shorter than this interval still fires exactly once, at its deadline)
// Hence a much longer default than CONDITIONAL_BRANCH_POLL_SECONDS; tunable via
// CDP_HOGFLOW_WAIT_UNTIL_SAFETY_POLL_SECONDS.
export const DEFAULT_WAIT_UNTIL_SAFETY_POLL_SECONDS = 60 * 60

export class ConditionalBranchHandler implements ActionHandler {
    constructor(private readonly waitUntilSafetyPollSeconds: number = DEFAULT_WAIT_UNTIL_SAFETY_POLL_SECONDS) {}

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
            action.type === 'wait_until_condition' ? this.waitUntilSafetyPollSeconds : CONDITIONAL_BRANCH_POLL_SECONDS
        )

        if (conditionResult.scheduledAt) {
            return { scheduledAt: conditionResult.scheduledAt, result: { conditionResult } }
        } else if (conditionResult.nextAction) {
            return { nextAction: conditionResult.nextAction, result: { conditionResult } }
        }

        return { nextAction: findContinueAction(invocation), result: { conditionResult } }
    }
}

export async function checkConditions(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>,
    pollSeconds: number = CONDITIONAL_BRANCH_POLL_SECONDS
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
        // Re-check on a timer until the condition matches or delay_duration elapses. `pollSeconds`
        // caps the gap between checks; calculatedScheduledAt clamps the final wake to the deadline.
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp,
            pollSeconds
        )

        if (scheduledAt) {
            return {
                scheduledAt,
            }
        }
    }
    return {}
}
