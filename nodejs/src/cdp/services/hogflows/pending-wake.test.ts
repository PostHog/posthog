import { HogFlowInvocationContext } from '~/cdp/types'

import { applyPendingWake } from './pending-wake'

describe('applyPendingWake', () => {
    const stateAtWait = (): HogFlowInvocationContext =>
        ({
            event: { uuid: 'trigger-uuid', event: 'app_opened' },
            currentAction: { id: 'wait_node', startedAtTimestamp: 0 },
        }) as unknown as HogFlowInvocationContext

    const later = { eventName: 'app_opened', eventUuid: 'later-uuid' }

    it.each([
        ['a later event', 'later-uuid', null, 'later-uuid'],
        ['the event that started the run', 'trigger-uuid', null, undefined],
        ['the event that started the run, then a later one', 'trigger-uuid', later, 'later-uuid'],
        [
            'the event that started the run, by a matcher that keeps no second match',
            'trigger-uuid',
            undefined,
            'trigger-uuid',
        ],
    ])('a match recorded for %s picks the event that wakes the wait', (_, eventUuid, next, wokenBy) => {
        const state = stateAtWait()

        applyPendingWake(state, {
            wait_node: {
                kind: 'match',
                at: '2026-01-01T00:00:00Z',
                eventName: 'app_opened',
                eventUuid,
                ...(next === undefined ? {} : { next }),
            },
        })

        expect(state.currentAction?.eventMatched && state.currentAction.eventMatchedEventUuid).toBe(wokenBy)
    })
})
