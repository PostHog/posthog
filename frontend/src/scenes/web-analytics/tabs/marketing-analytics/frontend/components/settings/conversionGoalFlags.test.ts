import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyMathType } from '~/types'

import { revenueDisabledReason, withValidFlags } from './conversionGoalFlags'

const goal = (overrides: Partial<ConversionGoalFilter> = {}): ConversionGoalFilter =>
    ({
        kind: NodeKind.EventsNode,
        event: 'purchase',
        conversion_goal_id: 'goal-1',
        conversion_goal_name: 'Purchase',
        schema_map: {},
        ...overrides,
    }) as ConversionGoalFilter

describe('revenueDisabledReason', () => {
    it('allows the flag once the goal sums a property', () => {
        expect(revenueDisabledReason(goal({ math: PropertyMathType.Sum, math_property: 'revenue' }))).toBeNull()
    })

    it('blocks counting math, which would divide spend by a conversion count', () => {
        expect(revenueDisabledReason(goal({ math: BaseMathType.TotalCount }))).toContain('Sum')
    })

    it('blocks sum math with no property, which sums nothing', () => {
        expect(revenueDisabledReason(goal({ math: PropertyMathType.Sum }))).toContain('property')
    })
})

describe('withValidFlags', () => {
    it('clears counts_as_revenue when math no longer qualifies', () => {
        const cleared = withValidFlags(goal({ math: BaseMathType.TotalCount, counts_as_revenue: true }))
        expect(cleared.counts_as_revenue).toBe(false)
    })

    it('leaves counts_as_customer alone, which has no math requirement', () => {
        const kept = withValidFlags(goal({ math: BaseMathType.TotalCount, counts_as_customer: true }))
        expect(kept.counts_as_customer).toBe(true)
    })

    it('keeps a valid revenue goal untouched', () => {
        const valid = goal({ math: PropertyMathType.Sum, math_property: 'revenue', counts_as_revenue: true })
        expect(withValidFlags(valid)).toBe(valid)
    })

    it('returns the same reference when the flag is already off', () => {
        // An unflagged goal with counting math has nothing to clear, so rebuilding it
        // would break identity for every caller comparing by reference.
        const unflagged = goal({ math: BaseMathType.TotalCount })
        expect(withValidFlags(unflagged)).toBe(unflagged)
    })
})
