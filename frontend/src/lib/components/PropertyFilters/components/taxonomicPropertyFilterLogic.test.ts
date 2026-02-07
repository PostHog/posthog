import { expectLogic } from 'kea-test-utils'

import { taxonomicPropertyFilterLogic } from 'lib/components/PropertyFilters/components/taxonomicPropertyFilterLogic'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

describe('the taxonomic property filter', () => {
    let logic: ReturnType<typeof taxonomicPropertyFilterLogic.build>

    beforeEach(() => {
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

    it('starts with dropdown closed', async () => {
        await expectLogic(logic).toMatchValues({
            dropdownOpen: false,
        })
    })

    it('closes the dropdown onCloseDropdown', async () => {
        await expectLogic(logic, () => {
            logic.actions.openDropdown()
            logic.actions.closeDropdown()
        }).toMatchValues({
            dropdownOpen: false,
        })
    })

    it('opens the dropdown onOpenDropdown', async () => {
        await expectLogic(logic, () => {
            logic.actions.openDropdown()
        }).toMatchValues({
            dropdownOpen: true,
        })
    })

    it('creates a complete property filter from a QuickFilterItem', async () => {
        const setFilter = jest.fn()
        const quickLogic = taxonomicPropertyFilterLogic({
            filters: [],
            setFilter,
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            filterIndex: 0,
            pageKey: 'testQuick',
        })
        quickLogic.mount()

        const quickFiltersGroup = {
            type: TaxonomicFilterGroupType.QuickFilters,
            name: 'Quick filters',
            searchPlaceholder: 'quick filters',
        } as TaxonomicFilterGroup

        const quickFilterItem = {
            name: 'Current URL containing "blog"',
            filterValue: 'blog',
            operator: PropertyOperator.IContains,
            propertyKey: '$current_url',
            propertyFilterType: PropertyFilterType.Event,
            eventName: '$pageview',
        }

        quickLogic.actions.selectItem(quickFiltersGroup, undefined, undefined, quickFilterItem)

        expect(setFilter).toHaveBeenCalledWith(0, {
            key: '$current_url',
            value: 'blog',
            operator: PropertyOperator.IContains,
            type: PropertyFilterType.Event,
        })

        quickLogic.unmount()
    })
})
