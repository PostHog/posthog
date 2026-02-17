import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { QuickFilterItem, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
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
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
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
            logic.actions.removeGroupValue(0)
        }).toMatchValues({
            filterGroup: { ...defaultFilter, values: [] },
        })
    })

    it('addGroupFilter', async () => {
        const property = {
            key: 'property_key',
            value: null,
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Person,
        }
        await expectLogic(logic, () => {
            logic.actions.addGroupFilter(
                { type: TaxonomicFilterGroupType.PersonProperties } as TaxonomicFilterGroup,
                'property_key',
                {}
            )
        }).toMatchValues({
            filterGroup: {
                ...defaultFilter,
                values: [...defaultFilter.values, property],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.addGroupFilter(
                { type: TaxonomicFilterGroupType.Events } as TaxonomicFilterGroup,
                'event_key',
                { name: 'Event name' }
            )
        }).toMatchValues({
            filterGroup: {
                ...defaultFilter,
                values: [
                    ...defaultFilter.values,
                    property,
                    {
                        id: 'event_key',
                        name: 'Event name',
                        type: 'events',
                    },
                ],
            },
        })
    })

    describe('addGroupFilter with QuickFilterItem', () => {
        it.each([
            {
                scenario: 'with event name and extra properties',
                item: {
                    _type: 'quick_filter' as const,
                    name: 'Pageview with email containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$current_url',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$pageview',
                    extraProperties: [
                        {
                            key: '$browser',
                            value: 'Chrome',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                } satisfies QuickFilterItem,
                expected: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: 'events',
                        properties: [
                            {
                                key: '$current_url',
                                value: 'blog',
                                operator: PropertyOperator.IContains,
                                type: PropertyFilterType.Event,
                            },
                            {
                                key: '$browser',
                                value: 'Chrome',
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    },
                ],
            },
            {
                scenario: 'without event name',
                item: {
                    _type: 'quick_filter' as const,
                    name: 'Person email containing "test"',
                    filterValue: 'test',
                    operator: PropertyOperator.IContains,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                } satisfies QuickFilterItem,
                expected: [
                    {
                        key: 'email',
                        value: 'test',
                        operator: PropertyOperator.IContains,
                        type: PropertyFilterType.Person,
                    },
                ],
            },
        ])('creates filters from QuickFilterItem $scenario', async ({ item, expected }) => {
            await expectLogic(logic, () => {
                logic.actions.addGroupFilter(
                    { type: TaxonomicFilterGroupType.SuggestedFilters } as TaxonomicFilterGroup,
                    undefined as any,
                    item
                )
            }).toMatchValues({
                filterGroup: {
                    ...defaultFilter,
                    values: [...defaultFilter.values, ...expected],
                },
            })
        })
    })
})
