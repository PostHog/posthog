import { PropertyOperator } from '~/types'

import { allOperatorsToHumanName } from './utils'

describe('allOperatorsToHumanName', () => {
    it.each([
        // Cohort operators have no symbol prefix and must not be sliced
        [PropertyOperator.In, 'in'],
        [PropertyOperator.NotIn, 'not in'],
        // Regular operators drop their 2-char symbol prefix
        [PropertyOperator.Exact, 'equals'],
        [PropertyOperator.IsNot, "doesn't equal"],
        [PropertyOperator.GreaterThan, 'greater than'],
        // Unknown / missing operator falls back to 'equals'
        [undefined, 'equals'],
        [null, 'equals'],
    ])('maps %s to "%s"', (operator, expected) => {
        expect(allOperatorsToHumanName(operator)).toBe(expected)
    })
})
