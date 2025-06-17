import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

// Opinionated version of the CyclotronJobInvocationResult limiting what an action can do
export type HogFlowActionRunnerResult = {
    action: HogFlowAction
    error?: unknown
    finished: boolean
    scheduledAt?: DateTime
    goToActionId?: string
}
