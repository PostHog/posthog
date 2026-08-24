import { HogFlow } from '~/cdp/schema/hogflow'

import { hasEvaluableWaitCondition, isEvaluableCondition } from './hogflow-utils'

describe('isEvaluableCondition', () => {
    it('treats a filter that targets nothing as absent (compiles to always-true)', () => {
        // These are exactly the shapes the compiler turns into always-true bytecode.
        expect(isEvaluableCondition(undefined)).toBe(false)
        expect(isEvaluableCondition({})).toBe(false)
        expect(isEvaluableCondition({ filters: {} })).toBe(false)
        expect(isEvaluableCondition({ filters: { properties: [] } })).toBe(false)
        expect(isEvaluableCondition({ filters: { properties: [], events: [], actions: [] } })).toBe(false)
        // A compiled empty condition still carries always-true bytecode, but it targets nothing.
        expect(isEvaluableCondition({ filters: { properties: [], bytecode: ['_H', 1, 29] } } as any)).toBe(false)
    })

    it('evaluates a real condition regardless of which filter field expresses it', () => {
        expect(isEvaluableCondition({ filters: { properties: [{ key: 'plan' }] } } as any)).toBe(true)
        // Expressed through events/actions (no top-level `properties`) — must still be evaluable.
        expect(isEvaluableCondition({ filters: { events: [{ id: '$pageview' }] } } as any)).toBe(true)
        expect(isEvaluableCondition({ filters: { actions: [{ id: 3 }] } } as any)).toBe(true)
        // Test-account filtering alone is a real filter (compiler emits team test-account predicates).
        expect(isEvaluableCondition({ filters: { filter_test_accounts: true } })).toBe(true)
    })
})

describe('hasEvaluableWaitCondition', () => {
    const flowWith = (actions: any[]): HogFlow => ({ actions }) as HogFlow

    it.each([
        [
            'a wait with a real condition',
            [{ type: 'wait_until_condition', config: { condition: { filters: { properties: [{ key: 'email' }] } } } }],
            true,
        ],
        [
            'a wait whose condition targets nothing',
            [{ type: 'wait_until_condition', config: { condition: { filters: { properties: [] } } } }],
            false,
        ],
        ['a wait with no condition at all (events-only)', [{ type: 'wait_until_condition', config: {} }], false],
        ['no wait step', [{ type: 'delay', config: { delay_duration: '1h' } }], false],
        [
            'a wait alongside other steps',
            [
                { type: 'delay', config: {} },
                { type: 'wait_until_condition', config: { condition: { filters: { properties: [{ key: 'plan' }] } } } },
            ],
            true,
        ],
    ])('%s', (_name, actions, expected) => {
        expect(hasEvaluableWaitCondition(flowWith(actions as any[]))).toBe(expected)
    })
})
