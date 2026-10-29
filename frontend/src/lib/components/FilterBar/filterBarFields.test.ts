import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

import {
    fieldFromFilter,
    filterWithOperator,
    filterWithToggledValue,
    isFilterComplete,
    newFilterForField,
    operatorLabelForFilter,
    operatorOptionsForFilter,
    valueLabelForFilter,
} from './filterBarFields'

const browser = (value: AnyPropertyFilter['value'], operator = PropertyOperator.Exact): AnyPropertyFilter =>
    ({ type: PropertyFilterType.Event, key: '$browser', operator, value }) as AnyPropertyFilter

describe('filterBarFields', () => {
    describe('newFilterForField', () => {
        it.each([
            ['cohorts', '12', undefined, { type: PropertyFilterType.Cohort, value: 12, operator: PropertyOperator.In }],
            ['sql', 'properties.x > 1', undefined, { type: PropertyFilterType.HogQL, key: 'properties.x > 1' }],
            ['event_properties', '$current_url', undefined, { operator: PropertyOperator.IContains }],
            ['person_properties', 'signed_up', PropertyType.DateTime, { operator: PropertyOperator.IsDateAfter }],
            [
                'session_properties',
                '$session_duration',
                PropertyType.Duration,
                { operator: PropertyOperator.GreaterThan },
            ],
            ['group_properties_2', 'plan', undefined, { type: PropertyFilterType.Group, group_type_index: 2 }],
        ] as const)('%s / %s builds the right filter', (categoryId, key, propertyType, expected) => {
            expect(newFilterForField({ categoryId, key, label: key, propertyType }, propertyType)).toMatchObject(
                expected
            )
        })
    })

    describe('isFilterComplete', () => {
        it.each([
            ['no value yet', browser(null), false],
            ['empty list', browser([]), false],
            ['one value', browser(['Chrome']), true],
            ['flag operator without value', browser(null, PropertyOperator.IsSet), true],
            ['sql expression', { type: PropertyFilterType.HogQL, key: 'true', value: null } as AnyPropertyFilter, true],
            [
                'cohort',
                {
                    type: PropertyFilterType.Cohort,
                    key: 'id',
                    value: 3,
                    operator: PropertyOperator.In,
                } as AnyPropertyFilter,
                true,
            ],
        ])('%s', (_, filter, complete) => {
            expect(isFilterComplete(filter)).toBe(complete)
        })
    })

    it('reads the operator as "is any of" once a list holds several values', () => {
        expect(operatorLabelForFilter(browser(['Chrome']))).toBe('is')
        expect(operatorLabelForFilter(browser(['Chrome', 'Safari']))).toBe('is any of')
        expect(operatorLabelForFilter(browser(['Chrome', 'Safari'], PropertyOperator.IsNot))).toBe('is none of')
    })

    it('summarizes the value segment of a chip', () => {
        expect(valueLabelForFilter(browser(null))).toEqual({ text: 'choose a value', placeholder: true })
        expect(valueLabelForFilter(browser(['Chrome', 'Safari', 'Edge']))).toEqual({
            text: 'Chrome, +2',
            placeholder: false,
        })
        expect(valueLabelForFilter(browser(null, PropertyOperator.IsNotSet)).text).toBe('')
        expect(
            valueLabelForFilter(
                { type: PropertyFilterType.Cohort, key: 'id', value: 3, operator: PropertyOperator.In },
                {
                    3: { id: 3, name: 'Power users' } as any,
                }
            ).text
        ).toBe('Power users')
    })

    it('toggles list values and replaces single values', () => {
        const toggled = filterWithToggledValue(browser(['Chrome']), 'Safari', 'list')
        expect(toggled).toMatchObject({ value: ['Chrome', 'Safari'] })
        expect(filterWithToggledValue(toggled, 'Chrome', 'list')).toMatchObject({ value: ['Safari'] })
        expect(filterWithToggledValue(browser(5), 7, 'number')).toMatchObject({ value: 7 })
    })

    it('drops the value when the new operator cannot use it', () => {
        expect(filterWithOperator(browser(['Chrome', 'Safari']), PropertyOperator.IsSet)).toMatchObject({ value: null })
        expect(filterWithOperator(browser(['Chrome', 'Safari']), PropertyOperator.IContains)).toMatchObject({
            value: ['Chrome'],
        })
        expect(filterWithOperator(browser(['Chrome', 'Safari']), PropertyOperator.IsNot)).toMatchObject({
            value: ['Chrome', 'Safari'],
        })
    })

    it('hides the semver operators until one is in use', () => {
        const plain = operatorOptionsForFilter(browser(['1.0']), PropertyType.String).map((option) => option.value)
        expect(plain).toContain(PropertyOperator.IContains)
        expect(plain).not.toContain(PropertyOperator.SemverEq)
        const semver = operatorOptionsForFilter(browser(['1.0'], PropertyOperator.SemverGt), PropertyType.String).map(
            (option) => option.value
        )
        expect(semver).toContain(PropertyOperator.SemverEq)
    })

    it('labels a cohort filter by its field, not the cohort', () => {
        expect(
            fieldFromFilter({ type: PropertyFilterType.Cohort, key: 'id', value: 3, operator: PropertyOperator.In })
        ).toEqual({ categoryId: 'cohorts', key: 'id', label: 'Cohort' })
        expect(fieldFromFilter(browser(['Chrome']))).toMatchObject({ categoryId: 'event_properties', label: 'Browser' })
        expect(
            fieldFromFilter({ type: PropertyFilterType.Event, key: '$feature/beta', operator: PropertyOperator.Exact })
        ).toMatchObject({ categoryId: 'feature_flags', label: 'beta' })
    })
})
