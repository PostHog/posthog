import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { allOperatorsToHumanName, genericOperatorToHumanName } from './utils'

describe('DefinitionPopover operator helpers', () => {
    describe('genericOperatorToHumanName', () => {
        it.each([
            [PropertyOperator.Exact, 'equals'],
            [PropertyOperator.GreaterThanOrEqual, 'greater than or equal'],
            [PropertyOperator.LessThanOrEqual, 'less than or equal'],
            [PropertyOperator.GreaterThan, 'greater than'],
            [PropertyOperator.IContains, 'contains'],
        ])('maps a typed property with operator %s to "%s"', (operator, expected) => {
            const property = { type: PropertyFilterType.Event, key: 'amount', value: 5, operator } as AnyPropertyFilter
            expect(genericOperatorToHumanName(property)).toBe(expected)
        })

        it('reads the operator from a legacy action step property that has no type', () => {
            // Legacy action step properties are stored without a `type` field
            const property = {
                key: 'amount',
                value: 5,
                operator: PropertyOperator.GreaterThanOrEqual,
            } as AnyPropertyFilter
            expect(genericOperatorToHumanName(property)).toBe('greater than or equal')
        })

        it.each([null, undefined, {} as AnyPropertyFilter])('falls back to "equals" for %s', (property) => {
            expect(genericOperatorToHumanName(property)).toBe('equals')
        })
    })

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
})
