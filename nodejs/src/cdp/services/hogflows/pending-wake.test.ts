import { HogFlowInvocationContext } from '~/cdp/types'

import { applyPendingWake } from './pending-wake'

describe('applyPendingWake', () => {
    const stateAtWait = (): HogFlowInvocationContext =>
        ({
            event: { uuid: 'trigger-uuid', event: 'app_opened' },
            currentAction: { id: 'wait_node', startedAtTimestamp: 0 },
        }) as unknown as HogFlowInvocationContext

    it.each([
        ['a later event', 'later-uuid', undefined, 'later-uuid'],
        ['the event that started the run', 'trigger-uuid', undefined, undefined],
        ['the event that started the run, then a later one', 'trigger-uuid', 'later-uuid', 'later-uuid'],
    ])(
        'a match recorded for %s wakes the wait on the first event that did not start the run',
        (_, eventUuid, nextUuid, wokenBy) => {
            const state = stateAtWait()

            applyPendingWake(state, {
                wait_node: {
                    kind: 'match',
                    at: '2026-01-01T00:00:00Z',
                    eventName: 'app_opened',
                    eventUuid,
                    ...(nextUuid ? { next: { eventName: 'app_opened', eventUuid: nextUuid } } : {}),
                },
            })

            expect(state.currentAction?.eventMatched && state.currentAction.eventMatchedEventUuid).toBe(wokenBy)
        }
    )
})
