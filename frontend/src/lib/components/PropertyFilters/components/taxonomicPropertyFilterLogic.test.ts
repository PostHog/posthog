import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/taxonomicPropertyFilterLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

describe('taxonomicPropertyFilterLogic', () => {
    let logic: ReturnType<typeof taxonomicPropertyFilterLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/property_definitions': { results: [], count: 0 },
            },
        })
        initKeaTests()
        logic = taxonomicPropertyFilterLogic({
            filters: [],
            setFilter: () => {},
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.Elements,
            ],
            filterIndex: 1,
            pageKey: 'test',
        })
        logic.mount()
    })

    describe('activeTaxonomicGroup selector', () => {
        it.each([
            {
                desc: 'person property filter → PersonProperties group',
                filterType: PropertyFilterType.Person,
                expectedGroup: TaxonomicFilterGroupType.PersonProperties,
            },
            {
                desc: 'event property filter → EventProperties group',
                filterType: PropertyFilterType.Event,
                expectedGroup: TaxonomicFilterGroupType.EventProperties,
            },
        ])('$desc', ({ filterType, expectedGroup }) => {
            logic.unmount()
            logic = taxonomicPropertyFilterLogic({
                filters: [
                    {
                        key: 'test_key',
                        type: filterType,
                        value: 'test_value',
                        operator: PropertyOperator.Exact,
                    },
                ],
                setFilter: () => {},
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
                filterIndex: 0,
                pageKey: `test-active-group-${filterType}`,
            })
            logic.mount()
            expect(logic.values.activeTaxonomicGroup?.type).toBe(expectedGroup)
        })

        it('defaults to first group when filter is empty', () => {
            logic.unmount()
            logic = taxonomicPropertyFilterLogic({
                filters: [{}] as any[],
                setFilter: () => {},
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
                filterIndex: 0,
                pageKey: 'test-active-group-empty',
            })
            logic.mount()
            expect(logic.values.activeTaxonomicGroup?.type).toBe(TaxonomicFilterGroupType.EventProperties)
        })
    })

    describe('selectItem filter conversion', () => {
        let setFilterSpy: jest.Mock

        beforeEach(() => {
            setFilterSpy = jest.fn()
            logic.unmount()
            logic = taxonomicPropertyFilterLogic({
                filters: [],
                setFilter: setFilterSpy,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                    TaxonomicFilterGroupType.FeatureFlags,
                    TaxonomicFilterGroupType.EventMetadata,
                ],
                filterIndex: 0,
                pageKey: 'test-conversion',
            })
            logic.mount()
        })

        it.each([
            {
                desc: 'event property',
                groupType: TaxonomicFilterGroupType.EventProperties,
                key: '$browser',
                itemType: PropertyFilterType.Event,
                expected: { key: '$browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
            },
            {
                desc: 'person property',
                groupType: TaxonomicFilterGroupType.PersonProperties,
                key: 'email',
                itemType: PropertyFilterType.Person,
                expected: { key: 'email', type: PropertyFilterType.Person },
            },
            {
                desc: 'cohort with parseInt and cohort_name',
                groupType: TaxonomicFilterGroupType.Cohorts,
                key: '42',
                itemType: PropertyFilterType.Cohort,
                item: { name: 'Power Users' },
                expected: { key: 'id', value: 42, type: PropertyFilterType.Cohort, cohort_name: 'Power Users' },
            },
            {
                desc: 'HogQL with null value',
                groupType: TaxonomicFilterGroupType.HogQLExpression,
                key: "properties.$browser = 'Chrome'",
                itemType: PropertyFilterType.HogQL,
                expected: { type: PropertyFilterType.HogQL, key: "properties.$browser = 'Chrome'", value: null },
            },
            {
                desc: 'feature flag with default true and FlagEvaluatesTo',
                groupType: TaxonomicFilterGroupType.FeatureFlags,
                key: 'beta-feature',
                itemType: PropertyFilterType.Flag,
                item: { key: 'beta-feature' },
                expected: {
                    type: PropertyFilterType.Flag,
                    key: 'beta-feature',
                    value: true,
                    operator: PropertyOperator.FlagEvaluatesTo,
                    label: 'beta-feature',
                },
            },
            {
                desc: 'EventMetadata $group_* with label from item name',
                groupType: TaxonomicFilterGroupType.EventMetadata,
                key: '$group_0',
                itemType: PropertyFilterType.EventMetadata,
                item: { id: '$group_0', name: 'Organization' },
                expected: { type: PropertyFilterType.EventMetadata, key: '$group_0', label: 'Organization' },
            },
        ])('$desc', ({ groupType, key, itemType, item, expected }) => {
            const group = logic.values.taxonomicGroups.find((g) => g.type === groupType)!
            logic.actions.selectItem(group, key, itemType, item)
            expect(setFilterSpy).toHaveBeenCalledWith(0, expect.objectContaining(expected))
        })

        it('closes the dropdown after selecting an item', () => {
            const group = logic.values.taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.EventProperties)!
            logic.actions.openDropdown()
            logic.actions.selectItem(group, '$browser', PropertyFilterType.Event)
            expect(logic.values.dropdownOpen).toBe(false)
        })

        it('does not call setFilter when propertyKey is undefined', () => {
            const group = logic.values.taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.EventProperties)!
            logic.actions.selectItem(group, undefined)
            expect(setFilterSpy).not.toHaveBeenCalled()
        })
    })
})
