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
            // Semver operators live outside the generic map and must still resolve, not fall back to "equals"
            [PropertyOperator.SemverGte, 'greater than or equal (semver)'],
        ])('maps a typed property with operator %s to "%s"', (operator, expected) => {
            const property = { type: PropertyFilterType.Event, key: 'amount', value: 5, operator } as AnyPropertyFilter
            expect(genericOperatorToHumanName(property)).toBe(expected)
        })

        it.each([
            [PropertyOperator.GreaterThanOrEqual, 'greater than or equal'],
            // Semver filters on e.g. $os_version (no `type` on the legacy step) — the reported bug
            [PropertyOperator.SemverGte, 'greater than or equal (semver)'],
            [PropertyOperator.SemverLte, 'less than or equal (semver)'],
            [PropertyOperator.SemverEq, 'equals (semver)'],
        ])('reads operator %s from a legacy action step property that has no type', (operator, expected) => {
            // Legacy action step properties are stored without a `type` field
            const property = { key: '$os_version', value: '14.4.1', operator } as AnyPropertyFilter
            expect(genericOperatorToHumanName(property)).toBe(expected)
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
