import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import {
    buildQuickFilterSuggestions,
    isHost,
    taxonomicFilterLogic,
} from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockSessionPropertyDefinitions } from '~/test/mocks'
import { AppContext, EventDefinition } from '~/types'

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
        const eventsListLogic = infiniteListLogic({
            ...logic.props,
            listGroupType: TaxonomicFilterGroupType.Events,
        })
        const sessionPropsListLogic = infiniteListLogic({
            ...logic.props,
            listGroupType: TaxonomicFilterGroupType.SessionProperties,
        })

        const waitForRemoteResults = async (fn?: () => void): Promise<void> => {
            await expectLogic(eventsListLogic, fn).toDispatchActions(['loadRemoteItemsSuccess'])
            await expectLogic(sessionPropsListLogic).toDispatchActions(['loadRemoteItemsSuccess']).delay(1)
        }

        // load the initial results
        await waitForRemoteResults()

        await waitForRemoteResults(() => logic.actions.setSearchQuery('event'))
        await expectLogic(logic).toMatchValues({
            searchQuery: 'event',
            activeTab: TaxonomicFilterGroupType.Events,
            infiniteListCounts: {
                [TaxonomicFilterGroupType.Events]: 4,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 0,
                [TaxonomicFilterGroupType.SessionProperties]: 0,
            },
        })

        await waitForRemoteResults(() => logic.actions.setSearchQuery('selector'))
        await expectLogic(logic).toMatchValues({
            searchQuery: 'selector',
            activeTab: TaxonomicFilterGroupType.Elements,
            infiniteListCounts: {
                [TaxonomicFilterGroupType.Events]: 0,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 1,
                [TaxonomicFilterGroupType.SessionProperties]: 0,
            },
        })

        await waitForRemoteResults(() => logic.actions.setSearchQuery('this is not found'))
        await expectLogic(logic).toMatchValues({
            searchQuery: 'this is not found',
            activeTab: TaxonomicFilterGroupType.Elements,
            infiniteListCounts: {
                [TaxonomicFilterGroupType.Events]: 0,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 0,
                [TaxonomicFilterGroupType.SessionProperties]: 0,
            },
        })

        await waitForRemoteResults(() => logic.actions.setSearchQuery(''))
        await expectLogic(logic).toMatchValues({
            searchQuery: '',
            activeTab: TaxonomicFilterGroupType.Elements,
            infiniteListCounts: {
                [TaxonomicFilterGroupType.Events]: 157,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 4,
                [TaxonomicFilterGroupType.SessionProperties]: 2,
            },
        })
    })

    it('tabs skip groups with no results', async () => {
        await expectLogic(logic).toDispatchActions(['infiniteListResultsReceived']).delay(1).clearHistory()

        // move right from Events, skipping Actions (0 results)
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Elements,
        })
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.SessionProperties,
        })
        await expectLogic(logic, () => logic.actions.tabRight()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Events,
        })

        // move left from Events, skipping Actions
        await expectLogic(logic, () => logic.actions.tabLeft()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.SessionProperties,
        })
        await expectLogic(logic, () => logic.actions.tabLeft()).toMatchValues({
            activeTab: TaxonomicFilterGroupType.Elements,
        })
    })

    describe('isHost', () => {
        it.each([
            { input: 'example.com', expected: true, description: 'simple domain' },
            { input: 'www.example.com', expected: true, description: 'www prefix' },
            { input: 'app.posthog.com', expected: true, description: 'subdomain' },
            { input: 'my-site.co.uk', expected: true, description: 'hyphenated with multi-part TLD' },
            { input: 'localhost', expected: true, description: 'localhost' },
            { input: 'blog', expected: false, description: 'single word' },
            { input: 'hello world', expected: false, description: 'contains spaces' },
            { input: 'https://example.com', expected: false, description: 'full URL' },
            { input: 'user@example.com', expected: false, description: 'email address' },
            { input: '', expected: false, description: 'empty string' },
            { input: '.example.com', expected: false, description: 'leading dot' },
            { input: 'example.', expected: false, description: 'trailing dot' },
        ])('$description ($input) -> $expected', ({ input, expected }) => {
            expect(isHost(input)).toBe(expected)
        })
    })

    describe('buildQuickFilterSuggestions only suggests for URLs, emails, and hosts', () => {
        const propertyModeGroupTypes = [
            TaxonomicFilterGroupType.SuggestedFilters,
            TaxonomicFilterGroupType.PageviewUrls,
        ]
        const eventModeGroupTypes = [
            TaxonomicFilterGroupType.SuggestedFilters,
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
        ]

        it.each([
            { query: '', groupTypes: propertyModeGroupTypes, description: 'empty query' },
            { query: 'blog', groupTypes: propertyModeGroupTypes, description: 'plain text in property mode' },
            { query: 'blog', groupTypes: eventModeGroupTypes, description: 'plain text in event mode' },
            { query: 'some random words', groupTypes: propertyModeGroupTypes, description: 'multiple words' },
            { query: '  \n  ', groupTypes: propertyModeGroupTypes, description: 'whitespace only' },
        ])('returns empty array for $description', ({ query, groupTypes }) => {
            expect(buildQuickFilterSuggestions(query, groupTypes)).toHaveLength(0)
        })

        it.each([
            {
                query: 'user@example.com',
                groupTypes: propertyModeGroupTypes,
                expectedNames: ['Email address = "user@example.com"', 'Email address containing "user@example.com"'],
                description: 'email in property mode shows exact + contains',
            },
            {
                query: 'user@example.com',
                groupTypes: eventModeGroupTypes,
                expectedNames: [
                    'Pageview with Email address = "user@example.com"',
                    'Screen with Email address = "user@example.com"',
                    'Pageview with Email address containing "user@example.com"',
                    'Screen with Email address containing "user@example.com"',
                ],
                description: 'email in event mode shows exact + contains with event context',
            },
            {
                query: 'https://posthog.com/pricing',
                groupTypes: propertyModeGroupTypes,
                expectedNames: [
                    'Current URL = "https://posthog.com/pricing"',
                    'Current URL containing "https://posthog.com/pricing"',
                    'Screen name containing "https://posthog.com/pricing"',
                ],
                description: 'URL in property mode shows exact URL, contains URL, and screen',
            },
            {
                query: 'posthog.com',
                groupTypes: propertyModeGroupTypes,
                expectedNames: ['Host = "posthog.com"'],
                description: 'host in property mode shows exact host match',
            },
            {
                query: 'app.posthog.com',
                groupTypes: eventModeGroupTypes,
                expectedNames: ['Pageview with Host = "app.posthog.com"'],
                description: 'host in event mode shows exact host match with event context',
            },
            {
                query: '  user@example.com\n',
                groupTypes: propertyModeGroupTypes,
                expectedNames: ['Email address = "user@example.com"', 'Email address containing "user@example.com"'],
                description: 'pasted email with whitespace is trimmed',
            },
        ])('$description', ({ query, groupTypes, expectedNames }) => {
            const results = buildQuickFilterSuggestions(query, groupTypes)
            expect(results.map((r) => r.name)).toEqual(expectedNames)
        })
    })

    describe('buildQuickFilterSuggestions filters by event existence', () => {
        it.each([
            {
                eventExistence: { hasPageview: false, hasScreen: true },
                query: 'https://example.com',
                description: 'URL: no pageview hides URL suggestions, keeps screen',
                expectedNames: ['Screen name containing "https://example.com"'],
            },
            {
                eventExistence: { hasPageview: true, hasScreen: false },
                query: 'https://example.com',
                description: 'URL: no screen hides screen suggestion, keeps URL',
                expectedNames: ['Current URL = "https://example.com"', 'Current URL containing "https://example.com"'],
            },
            {
                eventExistence: { hasPageview: false, hasScreen: true },
                query: 'posthog.com',
                description: 'host: no pageview hides host match',
                expectedNames: [],
            },
            {
                eventExistence: { hasPageview: true, hasScreen: false },
                query: 'user@example.com',
                description: 'email: no screen keeps email suggestions (no screen context in property mode)',
                expectedNames: ['Email address = "user@example.com"', 'Email address containing "user@example.com"'],
            },
        ])('$description', ({ eventExistence, query, expectedNames }) => {
            const propertyModeGroupTypes = [
                TaxonomicFilterGroupType.SuggestedFilters,
                TaxonomicFilterGroupType.PageviewUrls,
            ]
            const results = buildQuickFilterSuggestions(query, propertyModeGroupTypes, eventExistence)
            expect(results.map((r) => r.name)).toEqual(expectedNames)
        })
    })

    describe('QuickFilters shows top matches from other groups', () => {
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
                    TaxonomicFilterGroupType.SuggestedFilters,
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
                query: 'pageview',
                expectedMatchName: '$pageview',
                description: 'single result promotes even without exact name match',
            },
        ])('$description (query=$query)', async ({ query, expectedMatchName }) => {
            expect(quickLogic.values.activeTab).toBe(TaxonomicFilterGroupType.SuggestedFilters)

            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery(query)
            })
                .toDispatchActions(['setSearchQuery', 'appendTopMatches'])
                .delay(1)
                .toMatchValues({
                    activeTab: TaxonomicFilterGroupType.SuggestedFilters,
                    topMatchItems: [
                        expect.objectContaining({
                            name: expectedMatchName,
                            group: TaxonomicFilterGroupType.Events,
                        }),
                    ],
                })
        })

        it('promotes up to 3 top matches from other groups', async () => {
            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('event')
            })
                .toDispatchActions(['setSearchQuery', 'appendTopMatches'])
                .delay(1)
                .toMatchValues({
                    activeTab: TaxonomicFilterGroupType.SuggestedFilters,
                    topMatchItems: [
                        expect.objectContaining({ name: 'event1', group: TaxonomicFilterGroupType.Events }),
                        expect.objectContaining({ name: 'test event', group: TaxonomicFilterGroupType.Events }),
                        expect.objectContaining({ name: 'other event', group: TaxonomicFilterGroupType.Events }),
                    ],
                })
        })

        it('clears top match items on new search', async () => {
            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('$pageview')
            })
                .toDispatchActions(['setSearchQuery', 'appendTopMatches'])
                .delay(1)

            expect(quickLogic.values.topMatchItems).toHaveLength(1)

            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('blog')
            }).toMatchValues({
                topMatchItems: [],
            })
        })

        it('promotes top match from groups without getValue', async () => {
            const logicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: 'testNoGetValue',
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.InternalEventProperties,
                ],
            }
            const noGetValueLogic = taxonomicFilterLogic(logicProps)
            noGetValueLogic.mount()
            for (const listGroupType of logicProps.taxonomicGroupTypes) {
                infiniteListLogic({ ...logicProps, listGroupType }).mount()
            }

            expect(noGetValueLogic.values.activeTab).toBe(TaxonomicFilterGroupType.SuggestedFilters)

            await expectLogic(noGetValueLogic, () => {
                noGetValueLogic.actions.setSearchQuery('activity')
            })
                .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
                .delay(1)
                .clearHistory()
                .toMatchValues({
                    activeTab: TaxonomicFilterGroupType.SuggestedFilters,
                    topMatchItems: [
                        expect.objectContaining({
                            name: 'activity',
                            group: TaxonomicFilterGroupType.InternalEventProperties,
                        }),
                    ],
                })

            noGetValueLogic.unmount()
        })

        it('selecting a top match does not pass originalQuery', async () => {
            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('$pageview')
            })
                .toDispatchActions(['setSearchQuery', 'infiniteListResultsReceived'])
                .delay(1)

            expect(quickLogic.values.topMatchItems).toHaveLength(1)

            const quickListLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testQuickMatch',
                listGroupType: TaxonomicFilterGroupType.SuggestedFilters,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            })

            const totalCount = quickListLogic.values.totalListCount
            const lastItemIndex = totalCount - 1

            quickListLogic.actions.setIndex(lastItemIndex)

            await expectLogic(quickListLogic, () => {
                quickListLogic.actions.selectSelected()
            }).toDispatchActions([
                quickListLogic.actionCreators.selectSelected(),
                ({ type, payload }: { type: string; payload: any }) =>
                    type === quickListLogic.actionTypes.selectItem &&
                    payload.group.type === TaxonomicFilterGroupType.Events &&
                    payload.originalQuery === undefined,
            ])
        })
    })

    describe('QuickFilters opt-in', () => {
        it.each([
            {
                groupTypes: [TaxonomicFilterGroupType.SuggestedFilters, TaxonomicFilterGroupType.Events],
                flagValue: 'test',
                expectQuickFilters: true,
                description: 'includes QuickFilters when listed and flag enabled',
            },
            {
                groupTypes: [TaxonomicFilterGroupType.SuggestedFilters, TaxonomicFilterGroupType.Events],
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

            expect(testLogic.values.taxonomicGroupTypes.includes(TaxonomicFilterGroupType.SuggestedFilters)).toBe(
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
