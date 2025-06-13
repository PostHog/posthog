import { DateTime } from 'luxon'

// Opinionated version of the CyclotronJobInvocationResult limiting what an action can do
export type HogFlowActionRunnerResult = {
    finished: boolean
    scheduledAt?: DateTime
    goToActionId?: string
}
