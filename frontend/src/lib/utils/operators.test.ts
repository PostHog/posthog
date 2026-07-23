import {
    allOperatorsMapping,
    booleanOperatorMap,
    chooseOperatorMap,
    dateTimeOperatorMap,
    durationOperatorMap,
    genericOperatorMap,
    isOperatorMulti,
    numericOperatorMap,
    selectorOperatorMap,
    stringArrayOperatorMap,
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

        it('returns false for the starts_with/ends_with operator family', () => {
            expect(isOperatorMulti(PropertyOperator.StartsWith)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.NotStartsWith)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.EndsWith)).toBe(false)
            expect(isOperatorMulti(PropertyOperator.NotEndsWith)).toBe(false)
        })
    })

    describe('starts_with / ends_with operator family', () => {
        it.each([
            [PropertyOperator.StartsWith, 'starts with'],
            [PropertyOperator.NotStartsWith, "doesn't start with"],
            [PropertyOperator.EndsWith, 'ends with'],
            [PropertyOperator.NotEndsWith, "doesn't end with"],
        ])('exposes a "%s" label in the string operator maps and allOperatorsMapping', (operator, expectedText) => {
            expect(genericOperatorMap[operator]).toEqual(expect.stringContaining(expectedText))
            expect(stringOperatorMap[operator]).toEqual(expect.stringContaining(expectedText))
            expect(stringArrayOperatorMap[operator]).toEqual(expect.stringContaining(expectedText))
            expect(allOperatorsMapping[operator]).toEqual(expect.stringContaining(expectedText))
        })
    })
})
