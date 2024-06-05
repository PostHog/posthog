import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { UniversalFiltersGroup } from './UniversalFilters'
import { universalFiltersLogic } from './universalFiltersLogic'

const propertyFilter: AnyPropertyFilter = {
    key: '$geoip_country_code',
    value: ['GB'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Person,
}

const defaultFilter: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [propertyFilter],
        },
    ],
}

describe('universalFiltersLogic', () => {
    let logic: ReturnType<typeof universalFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = universalFiltersLogic({
            rootKey: 'test',
            group: defaultFilter,
            taxonomicEntityFilterGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            taxonomicPropertyFilterGroupTypes: [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
            ],
            onChange: () => {},
        })
        logic.mount()
    })

    it('taxonomicGroupTypes', async () => {
        await expectLogic(logic).toMatchValues({
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
            ],
        })
    })

    it('setGroupType', async () => {
        await expectLogic(logic, () => {
            logic.actions.setGroupType(FilterLogicalOperator.Or)
        }).toMatchValues({
            filterGroup: { ...defaultFilter, type: FilterLogicalOperator.Or },
        })
    })

    it('setGroupValues', async () => {
        await expectLogic(logic, () => {
            logic.actions.setGroupValues([])
        }).toMatchValues({
            filterGroup: { ...defaultFilter, values: [] },
        })
    })

    it('replaceGroupValue', async () => {
        await expectLogic(logic, () => {
            logic.actions.replaceGroupValue(0, propertyFilter)
        }).toMatchValues({
            filterGroup: { ...defaultFilter, values: [propertyFilter] },
        })
    })

    it('removeGroupValue', async () => {
        await expectLogic(logic, () => {
            logic.actions.replaceGroupValue(0)
        }).toMatchValues({
            filterGroup: { ...defaultFilter, values: [] },
        })
    })

    it('addGroupFilter', async () => {
        await expectLogic(logic, () => {
            logic.actions.addGroupFilter({ type: TaxonomicFilterGroupType.PersonProperties }, 'property_key', {})
        }).toMatchValues({
            filterGroup: {
                ...defaultFilter,
                values: [
                    ...defaultFilter.values,
                    {
                        key: 'property_key',
                        value: null,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Person,
                    },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.addGroupFilter({ type: TaxonomicFilterGroupType.Events }, 'event_key', {})
        }).toMatchValues({
            filterGroup: {
                ...defaultFilter,
                values: [
                    ...defaultFilter.values,
                    {
                        key: 'event_key',
                        value: null,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            },
        })
    })

    it('updateGroupFilter', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateGroupFilter(0, { ...propertyFilter, key: '$geoip_country_name' })
        }).toMatchValues({
            filterGroup: { ...defaultFilter, values: [{ ...propertyFilter, key: '$geoip_country_name' }] },
        })
    })
})
