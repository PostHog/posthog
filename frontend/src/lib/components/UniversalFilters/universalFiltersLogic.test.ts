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

    describe('taxonomicPropertyFilterGroupTypes', () => {
        it.each([
            { groupType: TaxonomicFilterGroupType.EventProperties, kept: true },
            { groupType: TaxonomicFilterGroupType.PersonProperties, kept: true },
            { groupType: TaxonomicFilterGroupType.SessionProperties, kept: true },
            { groupType: TaxonomicFilterGroupType.Replay, kept: true },
            { groupType: TaxonomicFilterGroupType.Cohorts, kept: true },
            { groupType: `${TaxonomicFilterGroupType.GroupsPrefix}_0` as TaxonomicFilterGroupType, kept: true },
            { groupType: TaxonomicFilterGroupType.EmailAddresses, kept: true },
            { groupType: TaxonomicFilterGroupType.PageviewUrls, kept: true },
            { groupType: TaxonomicFilterGroupType.RevenueAnalyticsProperties, kept: true },
            { groupType: TaxonomicFilterGroupType.Events, kept: false },
            { groupType: TaxonomicFilterGroupType.Actions, kept: false },
            { groupType: TaxonomicFilterGroupType.AutocaptureEvents, kept: false },
            { groupType: TaxonomicFilterGroupType.ReplaySavedFilters, kept: false },
            { groupType: TaxonomicFilterGroupType.SuggestedFilters, kept: false },
        ])('editing a pill keeps=$kept for $groupType', async ({ groupType, kept }) => {
            const scopedLogic = universalFiltersLogic({
                rootKey: 'scoped',
                group: defaultFilter,
                taxonomicGroupTypes: [groupType],
                onChange: () => {},
            })
            scopedLogic.mount()

            await expectLogic(scopedLogic).toMatchValues({
                taxonomicPropertyFilterGroupTypes: kept ? [groupType] : [],
            })
        })

        it('replay scene taxonomicGroupTypes yields correct property-filterable subset', async () => {
            const groups0 = `${TaxonomicFilterGroupType.GroupsPrefix}_0` as TaxonomicFilterGroupType
            const replaySceneGroupTypes = [
                TaxonomicFilterGroupType.SuggestedFilters,
                TaxonomicFilterGroupType.Replay,
                TaxonomicFilterGroupType.ReplaySavedFilters,
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.SessionProperties,
                groups0,
                TaxonomicFilterGroupType.AutocaptureEvents,
            ]

            const scopedLogic = universalFiltersLogic({
                rootKey: 'replay-regression',
                group: defaultFilter,
                taxonomicGroupTypes: replaySceneGroupTypes,
                onChange: () => {},
            })
            scopedLogic.mount()

            await expectLogic(scopedLogic).toMatchValues({
                taxonomicPropertyFilterGroupTypes: [
                    TaxonomicFilterGroupType.Replay,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.SessionProperties,
                    groups0,
                ],
            })
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

    it('addGroupFilter applies full property filter from recent taxonomic item', async () => {
        const fullFilter: AnyPropertyFilter = {
            key: '$browser',
            value: 'Chrome',
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }
        const item = {
            name: '$browser',
            _recentContext: {
                sourceGroupType: TaxonomicFilterGroupType.EventProperties,
                sourceGroupName: 'Event properties',
                propertyFilter: fullFilter,
            },
        }
        await expectLogic(logic, () => {
            logic.actions.addGroupFilter(
                { type: TaxonomicFilterGroupType.RecentFilters } as TaxonomicFilterGroup,
                '$browser',
                item
            )
        }).toMatchValues({
            filterGroup: {
                ...defaultFilter,
                values: [...defaultFilter.values, fullFilter],
            },
        })
    })

    it('addGroupFilter pre-fills value when search matched on a property value', async () => {
        await expectLogic(logic, () => {
            logic.actions.addGroupFilter(
                { type: TaxonomicFilterGroupType.PersonProperties } as TaxonomicFilterGroup,
                'user.email',
                { matchedOn: 'value', matchedValue: 'frank@posthog.com' } as any
            )
        }).toMatchValues({
            filterGroup: {
                ...defaultFilter,
                values: [
                    ...defaultFilter.values,
                    {
                        key: 'user.email',
                        value: ['frank@posthog.com'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Person,
                    },
                ],
            },
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

    describe('addGroupFilter with quick filter group types', () => {
        it.each([
            {
                groupType: TaxonomicFilterGroupType.PageviewUrls,
                propertyKey: 'https://example.com/blog',
                expected: {
                    key: '$current_url',
                    value: 'https://example.com/blog',
                    operator: PropertyOperator.IContains,
                    type: PropertyFilterType.Event,
                },
            },
            {
                groupType: TaxonomicFilterGroupType.Screens,
                propertyKey: 'HomeScreen',
                expected: {
                    key: '$screen_name',
                    value: 'HomeScreen',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            },
            {
                groupType: TaxonomicFilterGroupType.EmailAddresses,
                propertyKey: 'user@example.com',
                expected: {
                    key: 'email',
                    value: 'user@example.com',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Person,
                },
            },
        ])('creates a property filter for $groupType', async ({ groupType, propertyKey, expected }) => {
            await expectLogic(logic, () => {
                logic.actions.addGroupFilter({ type: groupType } as TaxonomicFilterGroup, propertyKey, {
                    name: propertyKey,
                })
            }).toMatchValues({
                filterGroup: {
                    ...defaultFilter,
                    values: [...defaultFilter.values, expected],
                },
            })
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
