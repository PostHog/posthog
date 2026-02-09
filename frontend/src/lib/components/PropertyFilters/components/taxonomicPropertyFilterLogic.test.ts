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
        function mountWithFilterType(filterType: PropertyFilterType.Person | PropertyFilterType.Event): void {
            logic.unmount()
            logic = taxonomicPropertyFilterLogic({
                filters: [{ key: 'test_key', type: filterType, value: 'test_value', operator: PropertyOperator.Exact }],
                setFilter: () => {},
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
                filterIndex: 0,
                pageKey: `test-active-group-${filterType}`,
            })
            logic.mount()
        }

        it('selects PersonProperties group for person property filter', () => {
            mountWithFilterType(PropertyFilterType.Person)
            expect(logic.values.activeTaxonomicGroup?.type).toBe(TaxonomicFilterGroupType.PersonProperties)
        })

        it('selects EventProperties group for event property filter', () => {
            mountWithFilterType(PropertyFilterType.Event)
            expect(logic.values.activeTaxonomicGroup?.type).toBe(TaxonomicFilterGroupType.EventProperties)
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

        function selectAndExpect(
            groupType: TaxonomicFilterGroupType,
            key: string,
            itemType: PropertyFilterType,
            expected: Record<string, any>,
            item?: Record<string, any>
        ): void {
            const group = logic.values.taxonomicGroups.find((g) => g.type === groupType)!
            logic.actions.selectItem(group, key, itemType, item)
            expect(setFilterSpy).toHaveBeenCalledWith(0, expect.objectContaining(expected))
        }

        it('creates event property filter with Exact operator', () => {
            selectAndExpect(TaxonomicFilterGroupType.EventProperties, '$browser', PropertyFilterType.Event, {
                key: '$browser',
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
            })
        })

        it('creates person property filter', () => {
            selectAndExpect(TaxonomicFilterGroupType.PersonProperties, 'email', PropertyFilterType.Person, {
                key: 'email',
                type: PropertyFilterType.Person,
            })
        })

        it('creates cohort filter with parseInt value and cohort_name', () => {
            selectAndExpect(
                TaxonomicFilterGroupType.Cohorts,
                '42',
                PropertyFilterType.Cohort,
                { key: 'id', value: 42, type: PropertyFilterType.Cohort, cohort_name: 'Power Users' },
                { name: 'Power Users' }
            )
        })

        it('creates HogQL filter with null value', () => {
            selectAndExpect(
                TaxonomicFilterGroupType.HogQLExpression,
                "properties.$browser = 'Chrome'",
                PropertyFilterType.HogQL,
                { type: PropertyFilterType.HogQL, key: "properties.$browser = 'Chrome'", value: null }
            )
        })

        it('creates feature flag filter with default true and FlagEvaluatesTo', () => {
            selectAndExpect(
                TaxonomicFilterGroupType.FeatureFlags,
                'beta-feature',
                PropertyFilterType.Flag,
                {
                    type: PropertyFilterType.Flag,
                    key: 'beta-feature',
                    value: true,
                    operator: PropertyOperator.FlagEvaluatesTo,
                    label: 'beta-feature',
                },
                { key: 'beta-feature' }
            )
        })

        it('creates EventMetadata filter with label from item name', () => {
            selectAndExpect(
                TaxonomicFilterGroupType.EventMetadata,
                '$group_0',
                PropertyFilterType.EventMetadata,
                { type: PropertyFilterType.EventMetadata, key: '$group_0', label: 'Organization' },
                { id: '$group_0', name: 'Organization' }
            )
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
