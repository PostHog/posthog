import { PropertyOperator } from '~/types'

import { type PropertyCondition, isCompleteCondition } from './propertyOperators'

describe('isCompleteCondition', () => {
    test.each<{ condition: PropertyCondition; complete: boolean }>([
        { condition: { operator: PropertyOperator.Exact, value: [] }, complete: false },
        { condition: { operator: PropertyOperator.Exact, value: [''] }, complete: false },
        { condition: { operator: PropertyOperator.IContains, value: '  ' }, complete: false },
        { condition: { operator: PropertyOperator.GreaterThan, value: 0 }, complete: true },
        { condition: { operator: PropertyOperator.Exact, value: ['Chrome'] }, complete: true },
        { condition: { operator: PropertyOperator.IsSet }, complete: true },
    ])('$condition.operator $condition.value is complete: $complete', ({ condition, complete }) => {
        expect(isCompleteCondition(condition)).toBe(complete)
    })
})
