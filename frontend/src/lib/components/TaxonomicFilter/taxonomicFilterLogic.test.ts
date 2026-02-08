import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    QuickFilterItem,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockSessionPropertyDefinitions } from '~/test/mocks'
import { AppContext, PropertyFilterType, PropertyOperator } from '~/types'

import { infiniteListLogic } from './infiniteListLogic'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

describe('taxonomicFilterLogic', () => {
    let logic: ReturnType<typeof taxonomicFilterLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': (res) => {
                    const search = res.url.searchParams.get('search')
                    const results = search
                        ? mockEventDefinitions.filter((e) => e.name.includes(search))
                        : mockEventDefinitions
                    return [
                        200,
                        {
                            results,
                            count: results.length,
                        },
                    ]
                },
                '/api/environments/:team/sessions/property_definitions': (res) => {
                    const search = res.url.searchParams.get('search')
                    const results = search
                        ? mockSessionPropertyDefinitions.filter((e) => e.name.includes(search))
                        : mockSessionPropertyDefinitions
                    return [
                        200,
                        {
                            results,
                            count: results.length,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()

        const logicProps: TaxonomicFilterLogicProps = {
            taxonomicFilterLogicKey: 'testList',
            taxonomicGroupTypes: [
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.Elements,
                TaxonomicFilterGroupType.SessionProperties,
            ],
        }
        logic = taxonomicFilterLogic(logicProps)
        logic.mount()

        // does not automatically mount these, but needs them
        for (const listGroupType of logicProps.taxonomicGroupTypes) {
            infiniteListLogic({ ...logicProps, listGroupType }).mount()
        }
    })

    it('mounts all infinite list logics', async () => {
        await expectLogic(logic).toMount([
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Events }),
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Actions }),
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Elements }),
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.SessionProperties }),
        ])
        expect(
            infiniteListLogic({ ...logic.props, listGroupType: TaxonomicFilterGroupType.Cohorts }).isMounted()
        ).toBeFalsy()
    })

    it('keeps infiniteListCounts in sync', async () => {
        await expectLogic(logic)
            .toMatchValues({
                infiniteListCounts: {
                    [TaxonomicFilterGroupType.Events]: 1,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 4,
                    [TaxonomicFilterGroupType.SessionProperties]: 0,
                },
            })
            .toDispatchActions(['infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                infiniteListCounts: {
                    [TaxonomicFilterGroupType.Events]: 157,
                    [TaxonomicFilterGroupType.Actions]: 0, // not mocked
                    [TaxonomicFilterGroupType.Elements]: 4,
                    [TaxonomicFilterGroupType.SessionProperties]: 2,
                },
            })
    })

    it('setting search query filters events', async () => {
        // load the initial results
        await expectLogic(logic).toDispatchActionsInAnyOrder([
            'infiniteListResultsReceived',
            'infiniteListResultsReceived',
        ])

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('event')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived', 'infiniteListResultsReceived'])
            .toMatchValues({
                searchQuery: 'event',
                activeTab: TaxonomicFilterGroupType.Events,
                infiniteListCounts: {
                    [TaxonomicFilterGroupType.Events]: 4,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 0,
                    [TaxonomicFilterGroupType.SessionProperties]: 0,
                },
            })

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('selector')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: 'selector',
                activeTab: TaxonomicFilterGroupType.Elements, // tab changed!
                infiniteListCounts: {
                    [TaxonomicFilterGroupType.Events]: 0,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 1,
                    [TaxonomicFilterGroupType.SessionProperties]: 0,
                },
            })

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('this is not found')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: 'this is not found',
                activeTab: TaxonomicFilterGroupType.Elements, // no change
                infiniteListCounts: {
                    [TaxonomicFilterGroupType.Events]: 0,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 0,
                    [TaxonomicFilterGroupType.SessionProperties]: 0,
                },
            })

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: '',
                activeTab: TaxonomicFilterGroupType.Elements, // no change
                infiniteListCounts: {
                    [TaxonomicFilterGroupType.Events]: 157,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 4,
                    [TaxonomicFilterGroupType.SessionProperties]: 2,
                },
            })

        // move right, skipping Actions
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.SessionProperties,
        })
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Events,
        })
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Elements,
        })

        // move left, skipping Actions
        await expectLogic(logic, () => logic.actions.tabLeft()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Events,
        })
        await expectLogic(logic, () => logic.actions.tabLeft()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.SessionProperties,
        })
        await expectLogic(logic, () => logic.actions.tabLeft()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Elements,
        })

        // open remote items tab after loading
        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('event')
        })
            .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                searchQuery: 'event',
                activeTab: TaxonomicFilterGroupType.Events, // changed!
                infiniteListCounts: {
                    [TaxonomicFilterGroupType.Events]: 4,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 0,
                    [TaxonomicFilterGroupType.SessionProperties]: 0,
                },
            })
    })

    describe('QuickFilters localItemsSearch', () => {
        let quickFilterSearch: (items: QuickFilterItem[], q: string) => QuickFilterItem[]

        beforeEach(() => {
            const quickFiltersLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: 'testQuickFilters',
                taxonomicGroupTypes: [TaxonomicFilterGroupType.QuickFilters, TaxonomicFilterGroupType.PageviewUrls],
            }
            const quickFiltersLogic = taxonomicFilterLogic(quickFiltersLogicProps)
            quickFiltersLogic.mount()

            const quickFiltersGroup = quickFiltersLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.QuickFilters
            )
            quickFilterSearch = quickFiltersGroup!.localItemsSearch! as typeof quickFilterSearch
        })

        it.each([
            { query: '', expectedLength: 0, description: 'empty query returns empty array' },
            {
                query: 'blog',
                expectedLength: 3,
                description: 'plain text returns pageview, screen, and email suggestions',
            },
            {
                query: 'user@example.com',
                expectedLength: 3,
                description: 'email returns exact email match first, then pageview, screen, no email contains',
            },
            {
                query: 'https://example.com/page',
                expectedLength: 4,
                description: 'URL returns exact URL match, then contains suggestions plus email',
            },
        ])('$description', ({ query, expectedLength }) => {
            expect(quickFilterSearch([], query)).toHaveLength(expectedLength)
        })

        it.each([
            {
                query: 'blog',
                index: 0,
                expected: {
                    name: 'Current URL containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$current_url',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$pageview',
                },
                description: 'property mode: plain text[0] is URL contains without event prefix',
            },
            {
                query: 'blog',
                index: 1,
                expected: {
                    name: 'Screen name containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$screen_name',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$screen',
                },
                description: 'property mode: plain text[1] is screen name contains without event prefix',
            },
            {
                query: 'blog',
                index: 2,
                expected: {
                    name: 'Email address containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                },
                description: 'property mode: plain text[2] is email contains',
            },
            {
                query: 'user@example.com',
                index: 0,
                expected: {
                    name: 'Email address = "user@example.com"',
                    filterValue: 'user@example.com',
                    operator: PropertyOperator.Exact,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                },
                description: 'property mode: email[0] is exact email match',
            },
            {
                query: 'https://posthog.com/pricing',
                index: 0,
                expected: {
                    name: 'Current URL = "https://posthog.com/pricing"',
                    filterValue: 'https://posthog.com/pricing',
                    operator: PropertyOperator.Exact,
                    propertyKey: '$current_url',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$pageview',
                },
                description: 'property mode: URL[0] is exact URL match without event prefix',
            },
        ])('$description', ({ query, index, expected }) => {
            const results = quickFilterSearch([], query)
            expect(results[index]).toEqual(expected)
        })
    })

    describe('QuickFilters localItemsSearch in event mode', () => {
        let quickFilterSearch: (items: QuickFilterItem[], q: string) => QuickFilterItem[]

        beforeEach(() => {
            const eventModeLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: 'testQuickFiltersEventMode',
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.QuickFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            }
            const eventModeLogic = taxonomicFilterLogic(eventModeLogicProps)
            eventModeLogic.mount()

            const quickFiltersGroup = eventModeLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.QuickFilters
            )
            quickFilterSearch = quickFiltersGroup!.localItemsSearch! as typeof quickFilterSearch
        })

        it.each([
            {
                query: 'blog',
                index: 0,
                expected: {
                    name: 'Pageview with Current URL containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$current_url',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$pageview',
                },
                description: 'event mode: plain text[0] includes event prefix',
            },
            {
                query: 'blog',
                index: 1,
                expected: {
                    name: 'Screen with Screen name containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$screen_name',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$screen',
                },
                description: 'event mode: plain text[1] includes event prefix',
            },
            {
                query: 'blog',
                index: 2,
                expected: {
                    name: 'Pageview with Email address containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$pageview',
                },
                description: 'event mode: plain text[2] email has pageview context',
            },
            {
                query: 'blog',
                index: 3,
                expected: {
                    name: 'Screen with Email address containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$screen',
                },
                description: 'event mode: plain text[3] email has screen context',
            },
            {
                query: 'user@example.com',
                index: 0,
                expected: {
                    name: 'Pageview with Email address = "user@example.com"',
                    filterValue: 'user@example.com',
                    operator: PropertyOperator.Exact,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$pageview',
                },
                description: 'event mode: email exact match[0] has pageview context',
            },
            {
                query: 'user@example.com',
                index: 1,
                expected: {
                    name: 'Screen with Email address = "user@example.com"',
                    filterValue: 'user@example.com',
                    operator: PropertyOperator.Exact,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$screen',
                },
                description: 'event mode: email exact match[1] has screen context',
            },
        ])('$description', ({ query, index, expected }) => {
            const results = quickFilterSearch([], query)
            expect(results[index]).toEqual(expected)
        })
    })

    describe('QuickFilters opt-in', () => {
        it.each([
            {
                groupTypes: [TaxonomicFilterGroupType.QuickFilters, TaxonomicFilterGroupType.Events],
                expectQuickFilters: true,
                description: 'includes QuickFilters when explicitly listed',
            },
            {
                groupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                expectQuickFilters: false,
                description: 'excludes QuickFilters when not listed',
            },
            {
                groupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
                expectQuickFilters: false,
                description: 'breakdown-like contexts without QuickFilters stay without it',
            },
        ])('$description', ({ groupTypes, expectQuickFilters }) => {
            const testLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: `testOptIn-${groupTypes.join('-')}`,
                taxonomicGroupTypes: groupTypes,
            }
            const testLogic = taxonomicFilterLogic(testLogicProps)
            testLogic.mount()

            expect(testLogic.values.taxonomicGroupTypes.includes(TaxonomicFilterGroupType.QuickFilters)).toBe(
                expectQuickFilters
            )

            testLogic.unmount()
        })
    })

    describe('maxContextOptions prop', () => {
        let maxLogic: ReturnType<typeof taxonomicFilterLogic.build>

        beforeEach(() => {
            const maxContextOptions = [
                { id: 'context1', name: 'Test Context 1', value: 'context1', icon: () => null },
                { id: 'context2', name: 'Test Context 2', value: 'context2', icon: () => null },
                { id: 'context3', name: 'Another Context', value: 'context3', icon: () => null },
            ]

            const logicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: 'testMaxContext',
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.MaxAIContext],
                maxContextOptions,
            }
            maxLogic = taxonomicFilterLogic(logicProps)
            maxLogic.mount()

            for (const listGroupType of logicProps.taxonomicGroupTypes) {
                infiniteListLogic({ ...logicProps, listGroupType }).mount()
            }
        })

        afterEach(() => {
            maxLogic.unmount()
        })

        it('includes MaxAI taxonomic group when maxContextOptions provided', () => {
            const taxonomicGroups = maxLogic.values.taxonomicGroups
            const maxAIGroup = taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.MaxAIContext)

            expect(maxAIGroup).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers
            expect(maxAIGroup?.name).toBe('On this page')
            expect(maxAIGroup?.searchPlaceholder).toBe('elements from this page')
            expect(maxAIGroup?.options).toEqual([
                { id: 'context1', name: 'Test Context 1', value: 'context1', icon: expect.anything() },
                { id: 'context2', name: 'Test Context 2', value: 'context2', icon: expect.anything() },
                { id: 'context3', name: 'Another Context', value: 'context3', icon: expect.anything() },
            ])
        })
    })
})
