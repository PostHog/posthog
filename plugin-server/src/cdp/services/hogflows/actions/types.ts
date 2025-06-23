import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

// Opinionated version of the CyclotronJobInvocationResult limiting what an action can do
export type HogFlowActionRunnerResult = {
    action: HogFlowAction
} & (
    | {
          // Indicates the workflow hit an exit and it is done (with optional error if one occurred)
          exited: true
          error?: unknown
      }
    | {
          // Indicates the workflow should continue to the next action
          exited: false
          goToAction: HogFlowAction
          scheduledAt?: DateTime
          error?: unknown // Error can still be added (for example if on_error is set to continue)
      }
    | {
          // Indicates the workflow should be scheduled for later but isn't moving on
          exited: false
          scheduledAt: DateTime
      }
)

export type HogFlowActionResult =
    | {
          // Indicates this action is complete
          done: true
          // Optionally can specify a go to action to move to
          goToAction?: HogFlowAction
          // Optionally can specify a scheduledAt to schedule for later
          scheduledAt?: DateTime
      }
    | {
          // Indicates that it should be scheduled for later without moving on
          done: false
          scheduledAt: DateTime
      }
