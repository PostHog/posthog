import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { recentItemsLogic } from 'lib/components/TaxonomicFilter/recentItemsLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockSessionPropertyDefinitions } from '~/test/mocks'
import { AppContext } from '~/types'

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

    describe('maxContextOptions prop', () => {
        let maxLogic: ReturnType<typeof taxonomicFilterLogic.build>

        beforeEach(() => {
            const maxContextOptions = [
                { id: 'context1', name: 'Test Context 1', value: 'context1', icon: null },
                { id: 'context2', name: 'Test Context 2', value: 'context2', icon: null },
                { id: 'context3', name: 'Another Context', value: 'context3', icon: null },
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
                { id: 'context1', name: 'Test Context 1', value: 'context1', icon: null },
                { id: 'context2', name: 'Test Context 2', value: 'context2', icon: null },
                { id: 'context3', name: 'Another Context', value: 'context3', icon: null },
            ])
        })
    })

    describe('recent items integration', () => {
        let recentLogic: ReturnType<typeof recentItemsLogic.build>
        let recentEventsLogic: ReturnType<typeof taxonomicFilterLogic.build>

        beforeEach(() => {
            recentLogic = recentItemsLogic()
            recentLogic.mount()
            recentLogic.actions.clearRecentEvents()
            recentLogic.actions.clearRecentProperties()

            const logicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: 'testRecentItems',
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.RecentEvents,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            }
            recentEventsLogic = taxonomicFilterLogic(logicProps)
            recentEventsLogic.mount()

            for (const listGroupType of logicProps.taxonomicGroupTypes) {
                infiniteListLogic({ ...logicProps, listGroupType }).mount()
            }
        })

        afterEach(() => {
            recentEventsLogic.unmount()
            recentLogic.unmount()
        })

        it('includes RecentEvents group in taxonomic groups', () => {
            const taxonomicGroups = recentEventsLogic.values.taxonomicGroups
            const recentGroup = taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.RecentEvents)

            expect(recentGroup).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers
            expect(recentGroup?.name).toBe('Recent events')
            expect(recentGroup?.searchPlaceholder).toBe('recent events')
        })

        it('includes RecentProperties group in taxonomic groups', () => {
            const taxonomicGroups = recentEventsLogic.values.taxonomicGroups
            const recentGroup = taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.RecentProperties)

            expect(recentGroup).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers
            expect(recentGroup?.name).toBe('Recent properties')
            expect(recentGroup?.searchPlaceholder).toBe('recent properties')
        })

        it('adds event to recent events when selected', async () => {
            const eventsGroup = recentEventsLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.Events
            )

            expect(eventsGroup).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers

            await expectLogic(recentEventsLogic, () => {
                recentEventsLogic.actions.selectItem(
                    eventsGroup!,
                    '$pageview',
                    { name: '$pageview', id: '1' },
                    undefined
                )
            })

            // Check that the recent item was added
            expect(recentLogic.values.recentEvents.length).toBe(1)
            expect(recentLogic.values.recentEvents[0].name).toBe('$pageview')
            expect(recentLogic.values.recentEvents[0].value).toBe('$pageview')
            expect(recentLogic.values.recentEvents[0].type).toBe(TaxonomicFilterGroupType.Events)
        })

        it('does not add to recent when selecting from RecentEvents tab', async () => {
            // First add an item
            recentLogic.actions.addRecentEvent({
                type: TaxonomicFilterGroupType.Events,
                value: '$pageview',
                name: '$pageview',
                timestamp: Date.now(),
            })

            const recentGroup = recentEventsLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.RecentEvents
            )

            expect(recentGroup).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers

            // Select from recent - should not add duplicate
            await expectLogic(recentEventsLogic, () => {
                recentEventsLogic.actions.selectItem(
                    recentGroup!,
                    '$pageview',
                    { name: '$pageview', value: '$pageview' },
                    undefined
                )
            })

            expect(recentLogic.values.recentEvents.length).toBe(1)
        })

        it('does not track items with null value', async () => {
            const eventsGroup = recentEventsLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.Events
            )

            await expectLogic(recentEventsLogic, () => {
                recentEventsLogic.actions.selectItem(
                    eventsGroup!,
                    null,
                    { name: 'All events', value: null },
                    undefined
                )
            })

            expect(recentLogic.values.recentEvents.length).toBe(0)
        })

        it('shows recent items in the RecentEvents group options', () => {
            recentLogic.actions.addRecentEvent({
                type: TaxonomicFilterGroupType.Events,
                value: '$pageview',
                name: '$pageview',
                timestamp: Date.now(),
            })
            recentLogic.actions.addRecentEvent({
                type: TaxonomicFilterGroupType.Events,
                value: '$autocapture',
                name: '$autocapture',
                timestamp: Date.now() + 100,
            })

            // Need to force re-evaluation of selectors
            const taxonomicGroups = recentEventsLogic.values.taxonomicGroups
            const recentGroup = taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.RecentEvents)

            expect(recentGroup?.options?.length).toBe(2)
            expect(recentGroup?.options?.[0].name).toBe('$autocapture')
            expect(recentGroup?.options?.[1].name).toBe('$pageview')
        })

        it('defaults to RecentEvents tab when it is first in the list', async () => {
            await expectLogic(recentEventsLogic).toMatchValues({
                activeTab: TaxonomicFilterGroupType.RecentEvents,
            })
        })
    })

    describe('recent properties integration', () => {
        let recentLogic: ReturnType<typeof recentItemsLogic.build>
        let recentPropsLogic: ReturnType<typeof taxonomicFilterLogic.build>

        beforeEach(() => {
            recentLogic = recentItemsLogic()
            recentLogic.mount()
            recentLogic.actions.clearRecentEvents()
            recentLogic.actions.clearRecentProperties()

            const logicProps: TaxonomicFilterLogicProps = {
                taxonomicFilterLogicKey: 'testRecentProperties',
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.RecentProperties,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            }
            recentPropsLogic = taxonomicFilterLogic(logicProps)
            recentPropsLogic.mount()

            for (const listGroupType of logicProps.taxonomicGroupTypes) {
                infiniteListLogic({ ...logicProps, listGroupType }).mount()
            }
        })

        afterEach(() => {
            recentPropsLogic.unmount()
            recentLogic.unmount()
        })

        it('adds property to recent properties when selected', async () => {
            const propsGroup = recentPropsLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.EventProperties
            )

            expect(propsGroup).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers

            await expectLogic(recentPropsLogic, () => {
                recentPropsLogic.actions.selectItem(propsGroup!, '$browser', { name: '$browser', id: '1' }, undefined)
            })

            expect(recentLogic.values.recentProperties.length).toBe(1)
            expect(recentLogic.values.recentProperties[0].name).toBe('$browser')
            expect(recentLogic.values.recentProperties[0].type).toBe(TaxonomicFilterGroupType.EventProperties)
        })

        it('adds person property to recent properties when selected', async () => {
            const propsGroup = recentPropsLogic.values.taxonomicGroups.find(
                (g) => g.type === TaxonomicFilterGroupType.PersonProperties
            )

            expect(propsGroup).toBeDefined() // oxlint-disable-line jest/no-restricted-matchers

            await expectLogic(recentPropsLogic, () => {
                recentPropsLogic.actions.selectItem(propsGroup!, 'email', { name: 'email', id: '1' }, undefined)
            })

            expect(recentLogic.values.recentProperties.length).toBe(1)
            expect(recentLogic.values.recentProperties[0].name).toBe('email')
            expect(recentLogic.values.recentProperties[0].type).toBe(TaxonomicFilterGroupType.PersonProperties)
        })

        it('shows recent properties in the RecentProperties group options', () => {
            recentLogic.actions.addRecentProperty({
                type: TaxonomicFilterGroupType.EventProperties,
                value: '$browser',
                name: '$browser',
                timestamp: Date.now(),
            })
            recentLogic.actions.addRecentProperty({
                type: TaxonomicFilterGroupType.PersonProperties,
                value: 'email',
                name: 'email',
                timestamp: Date.now() + 100,
            })

            const taxonomicGroups = recentPropsLogic.values.taxonomicGroups
            const recentGroup = taxonomicGroups.find((g) => g.type === TaxonomicFilterGroupType.RecentProperties)

            expect(recentGroup?.options?.length).toBe(2)
            expect(recentGroup?.options?.[0].name).toBe('email')
            expect(recentGroup?.options?.[1].name).toBe('$browser')
        })

        it('defaults to RecentProperties tab when it is first in the list', async () => {
            await expectLogic(recentPropsLogic).toMatchValues({
                activeTab: TaxonomicFilterGroupType.RecentProperties,
            })
        })
    })
})
