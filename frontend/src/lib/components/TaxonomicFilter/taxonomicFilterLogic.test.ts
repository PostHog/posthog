import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { buildQuickFilterSuggestions, taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockSessionPropertyDefinitions } from '~/test/mocks'
import { AppContext, EventDefinition, PropertyFilterType, PropertyOperator } from '~/types'

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
        featureFlagLogic.mount()
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

    describe('buildQuickFilterSuggestions in property mode', () => {
        const propertyModeGroupTypes = [TaxonomicFilterGroupType.QuickFilters, TaxonomicFilterGroupType.PageviewUrls]

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
            expect(buildQuickFilterSuggestions(query, propertyModeGroupTypes)).toHaveLength(expectedLength)
        })

        it.each([
            {
                query: 'blog',
                index: 0,
                expected: {
                    _type: 'quick_filter',
                    name: 'Current URL containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$current_url',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$pageview',
                },
                description: 'plain text[0] is URL contains without event prefix',
            },
            {
                query: 'blog',
                index: 1,
                expected: {
                    _type: 'quick_filter',
                    name: 'Screen name containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$screen_name',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$screen',
                },
                description: 'plain text[1] is screen name contains without event prefix',
            },
            {
                query: 'blog',
                index: 2,
                expected: {
                    _type: 'quick_filter',
                    name: 'Email address containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                },
                description: 'plain text[2] is email contains',
            },
            {
                query: 'user@example.com',
                index: 0,
                expected: {
                    _type: 'quick_filter',
                    name: 'Email address = "user@example.com"',
                    filterValue: 'user@example.com',
                    operator: PropertyOperator.Exact,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                },
                description: 'email[0] is exact email match',
            },
            {
                query: 'https://posthog.com/pricing',
                index: 0,
                expected: {
                    _type: 'quick_filter',
                    name: 'Current URL = "https://posthog.com/pricing"',
                    filterValue: 'https://posthog.com/pricing',
                    operator: PropertyOperator.Exact,
                    propertyKey: '$current_url',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$pageview',
                },
                description: 'URL[0] is exact URL match without event prefix',
            },
        ])('$description', ({ query, index, expected }) => {
            const results = buildQuickFilterSuggestions(query, propertyModeGroupTypes)
            expect(results[index]).toEqual(expected)
        })
    })

    describe('buildQuickFilterSuggestions in event mode', () => {
        const eventModeGroupTypes = [
            TaxonomicFilterGroupType.QuickFilters,
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
        ]

        it.each([
            {
                query: 'blog',
                index: 0,
                expected: {
                    _type: 'quick_filter',
                    name: 'Pageview with Current URL containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$current_url',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$pageview',
                },
                description: 'plain text[0] includes event prefix',
            },
            {
                query: 'blog',
                index: 1,
                expected: {
                    _type: 'quick_filter',
                    name: 'Screen with Screen name containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$screen_name',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$screen',
                },
                description: 'plain text[1] includes event prefix',
            },
            {
                query: 'blog',
                index: 2,
                expected: {
                    _type: 'quick_filter',
                    name: 'Clicked an element with text "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: '$el_text',
                    propertyFilterType: PropertyFilterType.Event,
                    eventName: '$autocapture',
                    extraProperties: [
                        {
                            key: '$event_type',
                            value: 'click',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                },
                description: 'plain text[2] autocapture click with element text',
            },
            {
                query: 'blog',
                index: 3,
                expected: {
                    _type: 'quick_filter',
                    name: 'Pageview with Email address containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$pageview',
                },
                description: 'plain text[3] email has pageview context',
            },
            {
                query: 'blog',
                index: 4,
                expected: {
                    _type: 'quick_filter',
                    name: 'Screen with Email address containing "blog"',
                    filterValue: 'blog',
                    operator: PropertyOperator.IContains,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$screen',
                },
                description: 'plain text[4] email has screen context',
            },
            {
                query: 'user@example.com',
                index: 0,
                expected: {
                    _type: 'quick_filter',
                    name: 'Pageview with Email address = "user@example.com"',
                    filterValue: 'user@example.com',
                    operator: PropertyOperator.Exact,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$pageview',
                },
                description: 'email exact match[0] has pageview context',
            },
            {
                query: 'user@example.com',
                index: 1,
                expected: {
                    _type: 'quick_filter',
                    name: 'Screen with Email address = "user@example.com"',
                    filterValue: 'user@example.com',
                    operator: PropertyOperator.Exact,
                    propertyKey: 'email',
                    propertyFilterType: PropertyFilterType.Person,
                    eventName: '$screen',
                },
                description: 'email exact match[1] has screen context',
            },
        ])('$description', ({ query, index, expected }) => {
            const results = buildQuickFilterSuggestions(query, eventModeGroupTypes)
            expect(results[index]).toEqual(expected)
        })
    })

    describe('buildQuickFilterSuggestions filters by event existence', () => {
        const propertyModeGroupTypes = [TaxonomicFilterGroupType.QuickFilters, TaxonomicFilterGroupType.PageviewUrls]
        const eventModeGroupTypes = [
            TaxonomicFilterGroupType.QuickFilters,
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
        ]

        it.each([
            {
                eventExistence: { hasPageview: false, hasScreen: true },
                groupTypes: propertyModeGroupTypes,
                query: 'blog',
                description: 'property mode: no pageview hides Current URL, keeps Screen name and email',
                expectedNames: ['Screen name containing "blog"', 'Email address containing "blog"'],
            },
            {
                eventExistence: { hasPageview: true, hasScreen: false },
                groupTypes: propertyModeGroupTypes,
                query: 'blog',
                description: 'property mode: no screen hides Screen name, keeps Current URL and email',
                expectedNames: ['Current URL containing "blog"', 'Email address containing "blog"'],
            },
            {
                eventExistence: { hasPageview: false, hasScreen: false },
                groupTypes: propertyModeGroupTypes,
                query: 'blog',
                description: 'property mode: no pageview or screen leaves only email',
                expectedNames: ['Email address containing "blog"'],
            },
            {
                eventExistence: { hasPageview: false, hasScreen: true },
                groupTypes: eventModeGroupTypes,
                query: 'blog',
                description: 'event mode: no pageview hides pageview items, keeps screen + autocapture + email',
                expectedNames: [
                    'Screen with Screen name containing "blog"',
                    'Clicked an element with text "blog"',
                    'Screen with Email address containing "blog"',
                ],
            },
            {
                eventExistence: { hasPageview: true, hasScreen: false },
                groupTypes: eventModeGroupTypes,
                query: 'blog',
                description: 'event mode: no screen hides screen items, keeps pageview + autocapture + email',
                expectedNames: [
                    'Pageview with Current URL containing "blog"',
                    'Clicked an element with text "blog"',
                    'Pageview with Email address containing "blog"',
                ],
            },
            {
                eventExistence: { hasPageview: false, hasScreen: false },
                groupTypes: eventModeGroupTypes,
                query: 'blog',
                description: 'event mode: no pageview or screen leaves only autocapture',
                expectedNames: ['Clicked an element with text "blog"'],
            },
        ])('$description', ({ eventExistence, groupTypes, query, expectedNames }) => {
            const results = buildQuickFilterSuggestions(query, groupTypes, eventExistence)
            expect(results.map((r) => r.name)).toEqual(expectedNames)
        })
    })

    describe('QuickFilters shows exact matches from other groups', () => {
        let quickLogic: ReturnType<typeof taxonomicFilterLogic.build>
        const eventsWithPageview: EventDefinition[] = [
            ...mockEventDefinitions,
            {
                id: 'uuid-pageview',
                name: '$pageview',
                description: 'Pageview event',
                tags: [],
                last_seen_at: '2022-01-24T21:32:38.359756Z',
            } as EventDefinition,
        ]

        beforeEach(() => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TAXONOMIC_QUICK_FILTERS]: 'test' })

            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': (res) => {
                        const search = res.url.searchParams.get('search')
                        const results = search
                            ? eventsWithPageview.filter((e) => e.name.toLowerCase().includes(search.toLowerCase()))
                            : eventsWithPageview
                        return [200, { results, count: results.length }]
                    },
                },
            })

            const logicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: 'testQuickMatch',
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.QuickFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            }
            quickLogic = taxonomicFilterLogic(logicProps)
            quickLogic.mount()
            for (const listGroupType of logicProps.taxonomicGroupTypes) {
                infiniteListLogic({ ...logicProps, listGroupType }).mount()
            }
        })

        afterEach(() => {
            quickLogic.unmount()
        })

        it.each([
            {
                query: '$pageview',
                expectedMatchName: '$pageview',
                description: 'exact name match promotes to QuickFilters',
            },
            {
                query: '$autocapture',
                expectedMatchName: '$autocapture',
                description: 'another exact name match promotes to QuickFilters',
            },
            {
                query: 'pageview',
                expectedMatchName: '$pageview',
                description: 'single result promotes even without exact name match',
            },
        ])('$description (query=$query)', async ({ query, expectedMatchName }) => {
            expect(quickLogic.values.activeTab).toBe(TaxonomicFilterGroupType.QuickFilters)

            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery(query)
            })
                .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
                .delay(1)
                .clearHistory()
                .toMatchValues({
                    activeTab: TaxonomicFilterGroupType.QuickFilters,
                    exactMatchItems: [
                        expect.objectContaining({
                            name: expectedMatchName,
                            group: TaxonomicFilterGroupType.Events,
                        }),
                    ],
                })
        })

        it('does not match when multiple results exist and none match exactly', async () => {
            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('event')
            })
                .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
                .delay(1)
                .clearHistory()
                .toMatchValues({
                    activeTab: TaxonomicFilterGroupType.QuickFilters,
                    exactMatchItems: [],
                })
        })

        it('promotes exact name match even when group returns multiple results', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': (res) => {
                        const search = res.url.searchParams.get('search')
                        const events = [
                            ...eventsWithPageview,
                            {
                                id: 'uuid-pageview-complete',
                                name: '$pageview_complete',
                                description: 'Pageview complete event',
                                tags: [],
                                last_seen_at: '2022-01-24T21:32:38.359756Z',
                            } as EventDefinition,
                        ]
                        const results = search
                            ? events.filter((e) => e.name.toLowerCase().includes(search.toLowerCase()))
                            : events
                        return [200, { results, count: results.length }]
                    },
                },
            })

            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('$pageview')
            })
                .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
                .delay(1)
                .clearHistory()
                .toMatchValues({
                    activeTab: TaxonomicFilterGroupType.QuickFilters,
                    exactMatchItems: [
                        expect.objectContaining({
                            name: '$pageview',
                            group: TaxonomicFilterGroupType.Events,
                        }),
                    ],
                })
        })

        it('clears exact match items on new search', async () => {
            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('$pageview')
            })
                .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
                .delay(1)

            expect(quickLogic.values.exactMatchItems).toHaveLength(1)

            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('blog')
            }).toMatchValues({
                exactMatchItems: [],
            })
        })
    })

    describe('QuickFilters opt-in', () => {
        it.each([
            {
                groupTypes: [TaxonomicFilterGroupType.QuickFilters, TaxonomicFilterGroupType.Events],
                flagValue: 'test',
                expectQuickFilters: true,
                description: 'includes QuickFilters when listed and flag enabled',
            },
            {
                groupTypes: [TaxonomicFilterGroupType.QuickFilters, TaxonomicFilterGroupType.Events],
                flagValue: 'control',
                expectQuickFilters: false,
                description: 'excludes QuickFilters when listed but flag disabled',
            },
            {
                groupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                flagValue: 'test',
                expectQuickFilters: false,
                description: 'excludes QuickFilters when not listed even with flag enabled',
            },
            {
                groupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
                flagValue: 'control',
                expectQuickFilters: false,
                description: 'breakdown-like contexts without QuickFilters stay without it',
            },
        ])('$description', ({ groupTypes, flagValue, expectQuickFilters }) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TAXONOMIC_QUICK_FILTERS]: flagValue })

            const testLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: `testOptIn-${flagValue}-${groupTypes.join('-')}`,
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
