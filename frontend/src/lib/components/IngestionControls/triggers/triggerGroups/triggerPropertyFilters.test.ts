import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { propertyFiltersToTriggerFilters } from './triggerPropertyFilters'

describe('propertyFiltersToTriggerFilters', () => {
    it('drops a row that has a key but no value yet', () => {
        const incomplete = [
            { key: 'browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
        ] as AnyPropertyFilter[]

        expect(propertyFiltersToTriggerFilters(incomplete)).toEqual([])
    })

    it.each([
        ['undefined value', undefined],
        ['null value', null],
        ['empty array', []],
    ])('drops a row with %s', (_label, value) => {
        const filters = [
            { key: 'browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value },
        ] as AnyPropertyFilter[]

        expect(propertyFiltersToTriggerFilters(filters)).toEqual([])
    })

    it('keeps a complete row and maps person type', () => {
        const filters = [
            { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IContains, value: 'a@b.com' },
        ] as AnyPropertyFilter[]

        expect(propertyFiltersToTriggerFilters(filters)).toEqual([
            { key: 'email', type: 'person', operator: 'icontains', value: 'a@b.com' },
        ])
    })

    it('keeps only complete rows when incomplete ones are interleaved', () => {
        const filters = [
            { key: 'browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: 'Chrome' },
            { key: 'os', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
        ] as AnyPropertyFilter[]

        expect(propertyFiltersToTriggerFilters(filters)).toEqual([
            { key: 'browser', type: 'event', operator: 'exact', value: 'Chrome' },
        ])
    })
})
