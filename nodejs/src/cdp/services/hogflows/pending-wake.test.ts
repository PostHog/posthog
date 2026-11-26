import { HogFlowInvocationContext } from '~/cdp/types'

import { applyPendingWake } from './pending-wake'

describe('applyPendingWake', () => {
    const stateAtWait = (): HogFlowInvocationContext =>
        ({
            event: { uuid: 'trigger-uuid', event: 'app_opened' },
            currentAction: { id: 'wait_node', startedAtTimestamp: 0 },
        }) as unknown as HogFlowInvocationContext

    it.each([
        ['a later event', 'later-uuid', true],
        ['the event that started the run', 'trigger-uuid', undefined],
    ])('a match recorded for %s sets eventMatched=%s', (_, eventUuid, expected) => {
        const state = stateAtWait()

        applyPendingWake(state, {
            wait_node: { kind: 'match', at: '2026-01-01T00:00:00Z', eventName: 'app_opened', eventUuid },
        })

        expect(state.currentAction?.eventMatched).toBe(expected)
    })
})
