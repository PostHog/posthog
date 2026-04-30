import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import {
    isSkeletonItem,
    propertyTaxonomicGroupProps,
    redistributeTopMatches,
    SKELETON_ROWS_PER_GROUP,
    taxonomicFilterLogic,
} from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockSessionPropertyDefinitions } from '~/test/mocks'
import { AppContext, EventDefinition, PropertyDefinition } from '~/types'

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
        for (const listGroupType of logic.values.taxonomicGroupTypes) {
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
                infiniteListCounts: expect.objectContaining({
                    [TaxonomicFilterGroupType.Events]: 1,
                    [TaxonomicFilterGroupType.Actions]: 0,
                    [TaxonomicFilterGroupType.Elements]: 4,
                    [TaxonomicFilterGroupType.SessionProperties]: 0,
                }),
            })
            .toDispatchActions(['infiniteListResultsReceived'])
            .delay(1)
            .clearHistory()
            .toMatchValues({
                infiniteListCounts: expect.objectContaining({
                    [TaxonomicFilterGroupType.Events]: 157,
                    [TaxonomicFilterGroupType.Actions]: 0, // not mocked
                    [TaxonomicFilterGroupType.Elements]: 4,
                    [TaxonomicFilterGroupType.SessionProperties]: 2,
                }),
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
            infiniteListCounts: expect.objectContaining({
                [TaxonomicFilterGroupType.Events]: 4,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 0,
                [TaxonomicFilterGroupType.SessionProperties]: 0,
            }),
        })

        await waitForRemoteResults(() => logic.actions.setSearchQuery('selector'))
        await expectLogic(logic).toMatchValues({
            searchQuery: 'selector',
            activeTab: TaxonomicFilterGroupType.Events,
            infiniteListCounts: expect.objectContaining({
                [TaxonomicFilterGroupType.Events]: 0,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 1,
                [TaxonomicFilterGroupType.SessionProperties]: 0,
            }),
        })

        await waitForRemoteResults(() => logic.actions.setSearchQuery('this is not found'))
        await expectLogic(logic).toMatchValues({
            searchQuery: 'this is not found',
            activeTab: TaxonomicFilterGroupType.Events,
            infiniteListCounts: expect.objectContaining({
                [TaxonomicFilterGroupType.Events]: 0,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 0,
                [TaxonomicFilterGroupType.SessionProperties]: 0,
            }),
        })

        await waitForRemoteResults(() => logic.actions.setSearchQuery(''))
        await expectLogic(logic).toMatchValues({
            searchQuery: '',
            activeTab: TaxonomicFilterGroupType.Events,
            infiniteListCounts: expect.objectContaining({
                [TaxonomicFilterGroupType.Events]: 157,
                [TaxonomicFilterGroupType.Actions]: 0,
                [TaxonomicFilterGroupType.Elements]: 4,
                [TaxonomicFilterGroupType.SessionProperties]: 2,
            }),
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

    describe('Suggested filters shows top matches from other groups', () => {
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

        it('collects top matches and redistributes via redistributedTopMatchItems', async () => {
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
                    redistributedTopMatchItems: [
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

        it.each([
            { description: 'undefined first entry', payload: [undefined as any] },
            { description: 'null first entry', payload: [null as any] },
            { description: 'entry missing group', payload: [{ name: 'anything' } as any] },
        ])('appendTopMatches is a no-op when $description', async ({ payload }) => {
            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery('$pageview')
            })
                .toDispatchActions(['setSearchQuery', 'appendTopMatches'])
                .delay(1)

            const before = quickLogic.values.topMatchItems
            expect(before).toHaveLength(1)

            expect(() => quickLogic.actions.appendTopMatches(payload)).not.toThrow()
            expect(quickLogic.values.topMatchItems).toEqual(before)
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

        it('selecting a top match dispatches selectItem with the correct group', async () => {
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
                    payload.group.type === TaxonomicFilterGroupType.Events,
            ])
        })

        it.each([
            {
                description: 'inserts skeleton placeholders for loading groups during search',
                query: 'zzz-will-not-match',
            },
            {
                description: 'inserts skeleton placeholders that are replaced by real results',
                query: 'event',
            },
        ])('$description (query=$query)', async ({ query }) => {
            const eventsListLogic = infiniteListLogic({
                ...quickLogic.props,
                listGroupType: TaxonomicFilterGroupType.Events,
            })

            await expectLogic(eventsListLogic).toDispatchActions(['loadRemoteItemsSuccess'])
            await expectLogic(quickLogic).delay(1)

            await expectLogic(quickLogic, () => {
                quickLogic.actions.setSearchQuery(query)
            }).toDispatchActions(['setSearchQuery'])

            const duringLoading = quickLogic.values.topMatchItemsWithSkeletons
            const skeletons = duringLoading.filter(isSkeletonItem)
            expect(skeletons).toHaveLength(SKELETON_ROWS_PER_GROUP)
            expect(skeletons.every((s) => s.group === TaxonomicFilterGroupType.Events)).toBe(true)
            expect(skeletons[0].groupName).toBe('Events')

            await expectLogic(eventsListLogic).toDispatchActions(['loadRemoteItemsSuccess'])
            await expectLogic(quickLogic).delay(1)

            const afterLoading = quickLogic.values.topMatchItemsWithSkeletons
            expect(afterLoading.filter(isSkeletonItem)).toHaveLength(0)
        })

        it('does not insert skeletons when search query is empty', async () => {
            const eventsListLogic = infiniteListLogic({
                ...quickLogic.props,
                listGroupType: TaxonomicFilterGroupType.Events,
            })
            await expectLogic(eventsListLogic).toDispatchActions(['loadRemoteItemsSuccess'])
            await expectLogic(quickLogic).delay(1)

            expect(quickLogic.values.searchQuery).toBe('')
            expect(quickLogic.values.topMatchItemsWithSkeletons).toEqual([])
        })
    })

    describe('SuggestedFilters presence', () => {
        it.each([
            {
                groupTypes: [TaxonomicFilterGroupType.SuggestedFilters, TaxonomicFilterGroupType.Events],
                expectQuickFilters: true,
                description: 'includes SuggestedFilters when listed in groupTypes',
            },
            {
                groupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                expectQuickFilters: false,
                description: 'excludes SuggestedFilters when not listed in groupTypes',
            },
        ])('$description', ({ groupTypes, expectQuickFilters }) => {
            const testLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: `testOptIn-${groupTypes.join('-')}`,
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

    describe('promoted groups are reordered', () => {
        it.each([
            {
                description: 'promotes PageviewUrls, Screens, EmailAddresses after SuggestedFilters and RecentFilters',
                groupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.EmailAddresses,
                ],
                expected: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.RecentFilters,
                    TaxonomicFilterGroupType.PinnedFilters,
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.EmailAddresses,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            },
            {
                description: 'promotes shortcut groups after auto-injected meta groups when no SuggestedFilters',
                groupTypes: [
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.EmailAddresses,
                ],
                expected: [
                    TaxonomicFilterGroupType.RecentFilters,
                    TaxonomicFilterGroupType.PinnedFilters,
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.EmailAddresses,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            },
            {
                description: 'auto-injects meta groups when no shortcut groups are present',
                groupTypes: [
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.EventProperties,
                ],
                expected: [
                    TaxonomicFilterGroupType.RecentFilters,
                    TaxonomicFilterGroupType.PinnedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.EventProperties,
                ],
            },
        ])('$description', ({ groupTypes, expected }) => {
            const testLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: `testReorder-${groupTypes.join('-')}`,
                taxonomicGroupTypes: groupTypes,
            }
            const testLogic = taxonomicFilterLogic(testLogicProps)
            testLogic.mount()

            expect(testLogic.values.taxonomicGroupTypes).toEqual(expected)

            testLogic.unmount()
        })
    })

    describe('autocapture context', () => {
        it.each([
            {
                description: 'SuggestedFilters has text/selector options when eventNames includes $autocapture',
                eventNames: ['$autocapture'],
                expectedOptions: [
                    { name: 'text', group: TaxonomicFilterGroupType.Elements },
                    { name: 'selector', group: TaxonomicFilterGroupType.Elements },
                ],
            },
            {
                description:
                    "SuggestedFilters surfaces the event's taxonomy-default primary property when eventNames=['$pageview']",
                eventNames: ['$pageview'],
                expectedOptions: [{ name: '$pathname', group: TaxonomicFilterGroupType.EventProperties }],
            },
            {
                description: 'SuggestedFilters has empty options when eventNames is empty',
                eventNames: [] as string[],
                expectedOptions: [],
            },
        ])('$description', ({ eventNames, expectedOptions }) => {
            const testLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: `testAutocaptureSuggested-${eventNames.join('-')}`,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.EventProperties,
                ],
                eventNames,
            }
            const testLogic = taxonomicFilterLogic(testLogicProps)
            testLogic.mount()

            const suggestedGroup = testLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.SuggestedFilters
            )
            expect(suggestedGroup?.options).toEqual(expectedOptions)

            testLogic.unmount()
        })

        it.each([
            {
                description: 'Elements group is promoted after SuggestedFilters when eventNames includes $autocapture',
                eventNames: ['$autocapture'],
                groupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.Elements,
                ],
                expected: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.RecentFilters,
                    TaxonomicFilterGroupType.PinnedFilters,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.EventProperties,
                ],
            },
            {
                description: 'Elements group stays in default position when eventNames does not include $autocapture',
                eventNames: ['$pageview'],
                groupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.Elements,
                ],
                expected: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.RecentFilters,
                    TaxonomicFilterGroupType.PinnedFilters,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.Elements,
                ],
            },
        ])('$description', ({ eventNames, groupTypes, expected }) => {
            const testLogicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: `testAutocapturePromotion-${eventNames.join('-')}`,
                taxonomicGroupTypes: groupTypes,
                eventNames,
            }
            const testLogic = taxonomicFilterLogic(testLogicProps)
            testLogic.mount()

            expect(testLogic.values.taxonomicGroupTypes).toEqual(expected)

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

    describe('keywordShortcuts on Events and EventProperties groups', () => {
        let testLogic: ReturnType<typeof taxonomicFilterLogic.build>

        beforeEach(() => {
            testLogic = taxonomicFilterLogic({
                taxonomicFilterLogicKey: 'keywordShortcutsGroupTest',
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties],
            })
            testLogic.mount()
        })

        afterEach(() => {
            testLogic.unmount()
        })

        it('Events group returns shortcuts with eventName set to $autocapture', () => {
            const eventsGroup = testLogic.values.taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.Events)
            expect(eventsGroup?.keywordShortcuts).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers
            const shortcuts = eventsGroup?.keywordShortcuts?.('click') ?? []
            expect(shortcuts[0]).toMatchObject({
                _type: 'quick_filter',
                name: 'Click (autocapture)',
                eventName: '$autocapture',
                filterValue: 'click',
            })
        })

        it('EventProperties group returns shortcuts without an eventName', () => {
            const eventPropertiesGroup = testLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.EventProperties
            )
            expect(eventPropertiesGroup?.keywordShortcuts).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers
            const [shortcut] = eventPropertiesGroup?.keywordShortcuts?.('click') ?? []
            expect(shortcut).toMatchObject({
                _type: 'quick_filter',
                name: 'Click (event type)',
                filterValue: 'click',
            })
            expect(shortcut.eventName).toBeUndefined()
        })

        it('Events group getName/getValue/getIcon/getPopoverHeader branch on isQuickFilterItem', () => {
            const eventsGroup = testLogic.values.taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.Events)
            const [shortcut] = eventsGroup?.keywordShortcuts?.('click') ?? []
            expect(eventsGroup?.getName?.(shortcut)).toBe('Click (autocapture)')
            expect(eventsGroup?.getValue?.(shortcut)).toEqual(expect.any(String))
            expect(eventsGroup?.getIcon?.(shortcut)).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers
            expect(eventsGroup?.getPopoverHeader(shortcut)).toBe('Autocapture shortcut')

            const realEvent = { id: 'uuid-evt', name: '$pageview' }
            expect(eventsGroup?.getName?.(realEvent)).toBe('$pageview')
            expect(eventsGroup?.getValue?.(realEvent)).toBe('$pageview')
        })

        it('EventProperties group popover header says "Event type shortcut" (not "Autocapture shortcut")', () => {
            const eventPropertiesGroup = testLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.EventProperties
            )
            const [shortcut] = eventPropertiesGroup?.keywordShortcuts?.('click') ?? []
            expect(eventPropertiesGroup?.getPopoverHeader(shortcut)).toBe('Event type shortcut')

            const realProperty = { name: '$current_url' } as any
            expect(eventPropertiesGroup?.getPopoverHeader(realProperty)).not.toBe('Event type shortcut')
        })

        it('shortcuts produce unique getValue keys so React selection stays stable', () => {
            const eventsGroup = testLogic.values.taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.Events)
            const shortcuts = eventsGroup?.keywordShortcuts?.('click') ?? []
            const values = shortcuts.map((s) => eventsGroup?.getValue?.(s))
            expect(new Set(values).size).toBe(values.length)
        })
    })
})

describe('redistributeTopMatches', () => {
    const makeItem = (name: string, group: TaxonomicFilterGroupType): any => ({ name, group })

    it.each([
        {
            description: 'returns empty output for empty input',
            items: [],
            activeGroupCount: 3,
            expected: [],
        },
        {
            description: 'no redistribution needed when all groups are within default slots',
            items: [
                ...Array.from({ length: 4 }, (_, i) => makeItem(`e${i + 1}`, TaxonomicFilterGroupType.Events)),
                makeItem('a1', TaxonomicFilterGroupType.Actions),
            ],
            activeGroupCount: 3,
            expected: [
                ...['e1', 'e2', 'e3', 'e4'].map((n) => expect.objectContaining({ name: n })),
                expect.objectContaining({ name: 'a1' }),
            ],
        },
        {
            description: 'empty groups give surplus slots to groups with extra items',
            items: Array.from({ length: 8 }, (_, i) => makeItem(`e${i + 1}`, TaxonomicFilterGroupType.Events)),
            activeGroupCount: 3,
            expected: Array.from({ length: 8 }, (_, i) => expect.objectContaining({ name: `e${i + 1}` })),
        },
        {
            description: '3+ groups with results caps each at DEFAULT_SLOTS_PER_GROUP without redistribution',
            items: [
                ...Array.from({ length: 8 }, (_, i) => makeItem(`ce${i + 1}`, TaxonomicFilterGroupType.CustomEvents)),
                ...Array.from({ length: 8 }, (_, i) => makeItem(`pu${i + 1}`, TaxonomicFilterGroupType.PageviewUrls)),
                ...Array.from({ length: 8 }, (_, i) => makeItem(`sc${i + 1}`, TaxonomicFilterGroupType.Screens)),
            ],
            activeGroupCount: 4,
            expected: [
                ...Array.from({ length: 5 }, (_, i) => expect.objectContaining({ name: `ce${i + 1}` })),
                ...Array.from({ length: 5 }, (_, i) => expect.objectContaining({ name: `pu${i + 1}` })),
                ...Array.from({ length: 5 }, (_, i) => expect.objectContaining({ name: `sc${i + 1}` })),
            ],
        },
        {
            description: 'fewer than 3 groups redistributes surplus with priority ordering',
            items: [
                ...Array.from({ length: 8 }, (_, i) => makeItem(`ce${i + 1}`, TaxonomicFilterGroupType.CustomEvents)),
                ...Array.from({ length: 8 }, (_, i) => makeItem(`pu${i + 1}`, TaxonomicFilterGroupType.PageviewUrls)),
            ],
            activeGroupCount: 4,
            expected: [
                ...Array.from({ length: 8 }, (_, i) => expect.objectContaining({ name: `ce${i + 1}` })),
                ...Array.from({ length: 8 }, (_, i) => expect.objectContaining({ name: `pu${i + 1}` })),
            ],
        },
        {
            description: 'surplus capped by available items in priority groups',
            items: [
                makeItem('ce1', TaxonomicFilterGroupType.CustomEvents),
                ...Array.from({ length: 8 }, (_, i) => makeItem(`e${i + 1}`, TaxonomicFilterGroupType.Events)),
            ],
            activeGroupCount: 5,
            expected: [
                expect.objectContaining({ name: 'ce1' }),
                ...Array.from({ length: 8 }, (_, i) => expect.objectContaining({ name: `e${i + 1}` })),
            ],
        },
        {
            description: 'without groupTypeOrder, preserves arrival order',
            items: [makeItem('a1', TaxonomicFilterGroupType.Actions), makeItem('e1', TaxonomicFilterGroupType.Events)],
            activeGroupCount: 2,
            expected: [
                expect.objectContaining({ name: 'a1', group: TaxonomicFilterGroupType.Actions }),
                expect.objectContaining({ name: 'e1', group: TaxonomicFilterGroupType.Events }),
            ],
        },
        {
            description: 'with groupTypeOrder, sorts groups by category order regardless of arrival order',
            items: [
                makeItem('a1', TaxonomicFilterGroupType.Actions),
                makeItem('dw1', TaxonomicFilterGroupType.DataWarehouse),
                makeItem('e1', TaxonomicFilterGroupType.Events),
            ],
            activeGroupCount: 3,
            groupTypeOrder: [
                TaxonomicFilterGroupType.Events,
                TaxonomicFilterGroupType.Actions,
                TaxonomicFilterGroupType.DataWarehouse,
            ],
            expected: [
                expect.objectContaining({ name: 'e1', group: TaxonomicFilterGroupType.Events }),
                expect.objectContaining({ name: 'a1', group: TaxonomicFilterGroupType.Actions }),
                expect.objectContaining({ name: 'dw1', group: TaxonomicFilterGroupType.DataWarehouse }),
            ],
        },
        {
            description: 'groupTypeOrder omits groups with no results',
            items: [makeItem('e1', TaxonomicFilterGroupType.Events)],
            activeGroupCount: 3,
            groupTypeOrder: [TaxonomicFilterGroupType.Actions, TaxonomicFilterGroupType.Events],
            expected: [expect.objectContaining({ name: 'e1', group: TaxonomicFilterGroupType.Events })],
        },
    ])('$description', ({ items, activeGroupCount, expected, groupTypeOrder }) => {
        expect(redistributeTopMatches(items, activeGroupCount, groupTypeOrder)).toEqual(expected)
    })
})

describe('isSkeletonItem', () => {
    it.each([
        {
            description: 'returns true for skeleton items',
            item: { _skeleton: true, group: TaxonomicFilterGroupType.Events, groupName: 'Events' },
            expected: true,
        },
        {
            description: 'returns false for regular items',
            item: { name: 'event1', group: TaxonomicFilterGroupType.Events },
            expected: false,
        },
        {
            description: 'returns false for null',
            item: null,
            expected: false,
        },
        {
            description: 'returns false for undefined',
            item: undefined,
            expected: false,
        },
    ])('$description', ({ item, expected }) => {
        expect(isSkeletonItem(item)).toBe(expected)
    })
})

describe('propertyTaxonomicGroupProps', () => {
    const makePropDef = (name: string): PropertyDefinition => ({ name }) as PropertyDefinition

    describe('person properties group labels only core person properties as PostHog properties', () => {
        const { getPopoverHeader } = propertyTaxonomicGroupProps(CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties)

        it.each([
            {
                property: 'email',
                expected: 'PostHog property',
                description: 'email is a core PostHog person property',
            },
            {
                property: '$email',
                expected: 'Property',
                description: '$email is not a core person property despite the $ prefix',
            },
            {
                property: 'emaill',
                expected: 'Property',
                description: 'misspelled emaill is a custom property',
            },
        ])('$description', ({ property, expected }) => {
            expect(getPopoverHeader!(makePropDef(property))).toBe(expected)
        })
    })

    describe('event properties group uses event_properties core definitions by default', () => {
        const { getPopoverHeader } = propertyTaxonomicGroupProps()

        it.each([
            {
                property: '$browser',
                expected: 'PostHog property',
                description: '$browser is a core PostHog event property',
            },
            {
                property: 'my_custom_prop',
                expected: 'Property',
                description: 'custom event properties are not labeled as PostHog properties',
            },
        ])('$description', ({ property, expected }) => {
            expect(getPopoverHeader!(makePropDef(property))).toBe(expected)
        })
    })
})
