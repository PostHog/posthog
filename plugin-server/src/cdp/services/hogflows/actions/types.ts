import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

// Opinionated version of the CyclotronJobInvocationResult limiting what an action can do
export type HogFlowActionRunnerResult = {
    action: HogFlowAction
    error?: unknown
    finished: boolean
    scheduledAt?: DateTime
    goToAction?: HogFlowAction
}

// TODO: Improve the type above so it is super clear what the outcome is
export type HogFlowActionRunnerResultOutcome = 'exited' | 'continued' | 'scheduled' | 'errored'

export type HogFlowActionResult = {
    // Indicates there is nothing more for the action to do
    finished: boolean
    // Indicates the flow should be scheduled for later
    scheduledAt?: DateTime
    // Indicates the next action to go to (and assumes it is finished)
    goToAction?: HogFlowAction
}
