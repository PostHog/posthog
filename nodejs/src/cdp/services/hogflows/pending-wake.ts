import { Counter } from 'prom-client'

import { PendingWake } from '~/cdp/services/cyclotron-v2/types'
import { HogFlowInvocationContext } from '~/cdp/types'

const counterPendingWakeApplied = new Counter({
    name: 'cdp_hogflow_pending_wake_applied_total',
    help: 'Wait wakes the matcher recorded while the run was in flight, applied when the run was next dequeued.',
    labelNames: ['kind'],
})

export function applyPendingWake(state: HogFlowInvocationContext, pendingWake: PendingWake | undefined): void {
    const currentAction = state.currentAction
    const entry = currentAction ? pendingWake?.[currentAction.id] : undefined
    if (!currentAction || !entry) {
        return
    }
    if (entry.kind === 'match') {
        currentAction.eventMatched = true
        currentAction.eventMatchedEvent = entry.eventName
        currentAction.eventMatchedEventUuid = entry.eventUuid
        currentAction.eventMatchedEventTimestamp = entry.eventTimestamp
    } else {
        currentAction.recheckWake = true
    }
    counterPendingWakeApplied.labels({ kind: entry.kind }).inc()
}
