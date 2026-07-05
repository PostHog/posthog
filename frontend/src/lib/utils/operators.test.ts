import {
    booleanOperatorMap,
    chooseOperatorMap,
    dateTimeOperatorMap,
    durationOperatorMap,
    genericOperatorMap,
    isOperatorMulti,
    isValidSemverValue,
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

    describe('isValidSemverValue', () => {
        // Mirrors the backend `parse_semver` gate: drift here re-introduces the save 400 for
        // non-semver values (or wrongly blocks a real version).
        it.each([
            ['1.2.3', PropertyOperator.SemverEq],
            ['1.2', PropertyOperator.SemverGt],
            ['1', PropertyOperator.SemverLt],
            ['1.2.3-alpha.1', PropertyOperator.SemverGte],
            ['1.2.3.4', PropertyOperator.SemverNeq], // extra components ignored, as on the backend
            ['1.2.*', PropertyOperator.SemverWildcard],
            ['1.*', PropertyOperator.SemverWildcard],
        ])('accepts %s for %s', (value, operator) => {
            expect(isValidSemverValue(value, operator)).toBe(true)
        })

        it.each([
            ['user@example.com', PropertyOperator.SemverEq],
            ['deadbeef', PropertyOperator.SemverNeq],
            ['1.', PropertyOperator.SemverGt],
            ['v1.2.3', PropertyOperator.SemverEq], // backend `int('v1')` rejects a leading v
            ['', PropertyOperator.SemverEq],
        ])('rejects %s for %s', (value, operator) => {
            expect(isValidSemverValue(value, operator)).toBe(false)
        })

        it('rejects a non-string value', () => {
            expect(isValidSemverValue(['1.2.3'], PropertyOperator.SemverEq)).toBe(false)
            expect(isValidSemverValue(null, PropertyOperator.SemverEq)).toBe(false)
        })
    })
})
