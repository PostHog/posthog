import {
    booleanOperatorMap,
    chooseOperatorMap,
    dateTimeOperatorMap,
    durationOperatorMap,
    genericOperatorMap,
    isOperatorMulti,
    numericOperatorMap,
    selectorOperatorMap,
    stringOperatorMap,
} from 'lib/utils/operators'

import { PropertyOperator, PropertyType } from '~/types'

describe('operators utils', () => {
    describe('choosing an operator for taxonomic filters', () => {
        const testCases = [
            { propertyType: PropertyType.DateTime, expected: dateTimeOperatorMap },
            { propertyType: PropertyType.String, expected: stringOperatorMap },
            { propertyType: PropertyType.Numeric, expected: numericOperatorMap },
            { propertyType: PropertyType.Boolean, expected: booleanOperatorMap },
            { propertyType: PropertyType.Duration, expected: durationOperatorMap },
            { propertyType: PropertyType.Selector, expected: selectorOperatorMap },
            { propertyType: undefined, expected: genericOperatorMap },
        ]
        testCases.forEach((testcase) => {
            it(`correctly maps ${testcase.propertyType} to operator options`, () => {
                expect(chooseOperatorMap(testcase.propertyType)).toEqual(testcase.expected)
            })
        })
    })

    describe('isOperatorMulti', () => {
        it('returns true for operators that support multiple values', () => {
            expect(isOperatorMulti(PropertyOperator.Exact)).toBe(true)
            expect(isOperatorMulti(PropertyOperator.IsNot)).toBe(true)
            expect(isOperatorMulti(PropertyOperator.IContainsMulti)).toBe(true)
            expect(isOperatorMulti(PropertyOperator.NotIContainsMulti)).toBe(true)
        })

        it('returns false for operators that do not support multiple values', () => {
            expect(isOperatorMulti(PropertyOperator.IContains)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.NotIContains)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.GreaterThan)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.LessThan)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.IsSet)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.IsNotSet)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.Regex)).toBe(false)
        })
    })
})
