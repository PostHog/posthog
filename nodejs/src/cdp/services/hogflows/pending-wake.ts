import { Counter } from 'prom-client'

import { PendingWake, PendingWakeEntry } from '~/cdp/services/cyclotron-v2/types'
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

export type WaitMatchEvent = Pick<PendingWakeEntry, 'eventName' | 'eventUuid' | 'eventTimestamp'>

// The matcher reads the same events that start runs, so a run's own trigger event can match its wait,
// and whether that match lands depends only on whether the run parked first. It never ends the wait.
export function matchNotFromTrigger(
    state: HogFlowInvocationContext,
    ...matches: (WaitMatchEvent | null | undefined)[]
): WaitMatchEvent | undefined {
    return matches.find((m): m is WaitMatchEvent => !!m && !(m.eventUuid && m.eventUuid === state.event?.uuid))
}

export function applyPendingWake(state: HogFlowInvocationContext, pendingWake: PendingWake | undefined): void {
    const currentAction = state.currentAction
    const entry = currentAction ? pendingWake?.[currentAction.id] : undefined
    if (!currentAction || !entry) {
        return
    }
    if (entry.kind === 'match') {
        // An entry with no `next` key comes from a matcher that never looks for a second match, so
        // dropping its trigger event could lose a real one hidden behind it. It wakes as written.
        const match = matchNotFromTrigger(state, entry, entry.next) ?? (entry.next === undefined ? entry : undefined)
        if (!match) {
            counterWaitWakeByTriggerEventIgnored.labels({ path: 'in_flight' }).inc()
            return
        }
        currentAction.eventMatched = true
        currentAction.eventMatchedEvent = match.eventName
        currentAction.eventMatchedEventUuid = match.eventUuid
        currentAction.eventMatchedEventTimestamp = match.eventTimestamp
    } else {
        currentAction.recheckWake = true
    }
    counterPendingWakeApplied.labels({ kind: entry.kind }).inc()
}
