import { Counter } from 'prom-client'

import { PendingWake } from '~/cdp/services/cyclotron-v2/types'
import { HogFlowInvocationContext } from '~/cdp/types'

const counterPendingWakeApplied = new Counter({
    name: 'cdp_hogflow_pending_wake_applied_total',
    help: 'Wait wakes the matcher recorded while the run was in flight, applied when the run was next dequeued.',
    labelNames: ['kind'],
})

export const counterWaitWakeByTriggerEventIgnored = new Counter({
    name: 'cdp_hogflow_wait_wake_by_trigger_event_ignored_total',
    help: 'Wait wakes dropped because the matched event is the one that started the run.',
    labelNames: ['path'],
})

// The matcher reads the same events that start runs. Without this check, a run's own trigger event
// could end its wait, depending only on whether the run parked before the matcher reached that event.
export function isRunTriggerEvent(state: HogFlowInvocationContext, eventUuid: string | undefined): boolean {
    return !!eventUuid && eventUuid === state.event?.uuid
}

export function applyPendingWake(state: HogFlowInvocationContext, pendingWake: PendingWake | undefined): void {
    const currentAction = state.currentAction
    const entry = currentAction ? pendingWake?.[currentAction.id] : undefined
    if (!currentAction || !entry) {
        return
    }
    if (entry.kind === 'match') {
        if (isRunTriggerEvent(state, entry.eventUuid)) {
            counterWaitWakeByTriggerEventIgnored.labels({ path: 'in_flight' }).inc()
            return
        }
        currentAction.eventMatched = true
        currentAction.eventMatchedEvent = entry.eventName
        currentAction.eventMatchedEventUuid = entry.eventUuid
        currentAction.eventMatchedEventTimestamp = entry.eventTimestamp
    } else {
        currentAction.recheckWake = true
    }
    counterPendingWakeApplied.labels({ kind: entry.kind }).inc()
}
