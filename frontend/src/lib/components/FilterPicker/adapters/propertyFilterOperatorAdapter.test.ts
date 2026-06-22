import { PropertyOperator, PropertyType } from '~/types'

import { createFilterPickerOperatorOptions, resolveDefaultOperator } from './propertyFilterOperatorAdapter'

describe('createFilterPickerOperatorOptions', () => {
    it('does not offer semver operators on plain string properties', () => {
        const operators = createFilterPickerOperatorOptions(PropertyType.String).map((option) => option.operator)
        expect(operators).toContain(PropertyOperator.IContains)
        expect(operators).not.toContain(PropertyOperator.SemverEq)
    })

    it('offers the semver operators only for the semver category', () => {
        const operators = createFilterPickerOperatorOptions(PropertyType.Semver).map((option) => option.operator)
        expect(operators).toContain(PropertyOperator.SemverEq)
        expect(operators).not.toContain(PropertyOperator.IContains)
    })

    it('surfaces the default operator first', () => {
        const operators = createFilterPickerOperatorOptions(
            PropertyType.DateTime,
            undefined,
            PropertyOperator.IsDateAfter
        )
        expect(operators[0].operator).toBe(PropertyOperator.IsDateAfter)
    })

    it('labels cohort in/not-in as the verb, not "user"', () => {
        const operators = createFilterPickerOperatorOptions(PropertyType.Cohort)
        const inOption = operators.find((option) => option.operator === PropertyOperator.In)
        expect(inOption?.menuLabel).toBe('in')
        expect(inOption?.tokenLabel).toBe('in')
    })

    it('honours an explicit allowlist over the type policy', () => {
        const operators = createFilterPickerOperatorOptions(PropertyType.String, [PropertyOperator.Exact]).map(
            (option) => option.operator
        )
        expect(operators).toEqual([PropertyOperator.Exact])
    })
})

describe('resolveDefaultOperator', () => {
    it('returns the type default', () => {
        expect(resolveDefaultOperator(PropertyType.Cohort)).toBe(PropertyOperator.In)
        expect(resolveDefaultOperator(PropertyType.Semver)).toBe(PropertyOperator.SemverEq)
    })

    it('prefers a per-property override', () => {
        expect(resolveDefaultOperator(PropertyType.String, PropertyOperator.SemverEq)).toBe(PropertyOperator.SemverEq)
    })

    it('is undefined when no default exists', () => {
        expect(resolveDefaultOperator(PropertyType.String)).toBeUndefined()
    })
})
