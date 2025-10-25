import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockEventPropertyDefinitions } from '~/test/mocks'
import { AppContext, PropertyDefinition } from '~/types'

import { infiniteListLogic } from './infiniteListLogic'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

describe('infiniteListLogic', () => {
    let logic: ReturnType<typeof infiniteListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': (req) => {
                    const search = req.url.searchParams.get('search')
                    const limit = Number(req.url.searchParams.get('limit'))
                    const offset = Number(req.url.searchParams.get('offset'))
                    const results = search
                        ? mockEventDefinitions.filter((e) => e.name.includes(search))
                        : mockEventDefinitions
                    const paginatedResults = results.filter((_, index) => index >= offset && index < offset + limit)

                    return [
                        200,
                        {
                            results: paginatedResults,
                            count: results.length,
                        },
                    ]
                },
                '/api/projects/:team/property_definitions': (req) => {
                    const search = req.url.searchParams.get('search')
                    let results = search
                        ? mockEventPropertyDefinitions.filter((e) => e.name.includes(search))
                        : mockEventPropertyDefinitions
                    if (req.url.searchParams.has('filter_by_event_names')) {
                        const isEventProperty = req.url.searchParams.get('filter_by_event_names') === 'true'
                        results = results.filter(
                            (e: PropertyDefinition) => e.is_seen_on_filtered_events === isEventProperty
                        )
                    }
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
    })

    const logicWith = (props: Record<string, any>): ReturnType<typeof infiniteListLogic.build> => {
        const defaultProps = {
            taxonomicFilterLogicKey: 'testList',
            listGroupType: TaxonomicFilterGroupType.Events,
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
            showNumericalPropsOnly: false,
        }
        const logicWithProps = infiniteListLogic({ ...defaultProps, ...props })
        logicWithProps.mount()
        return logicWithProps
    }

    describe('index', () => {
        it('defaults to 0 when whether the first item should be selected is not specified', async () => {
            await expectLogic(logicWith({})).toMatchValues({
                index: 0,
            })
        })

        it('is 0 when the first item should be selected', async () => {
            await expectLogic(logicWith({ selectFirstItem: true })).toMatchValues({
                index: 0,
            })
        })

        it('is -1 when first item should not be selected', async () => {
            await expectLogic(logicWith({ selectFirstItem: false })).toMatchValues({
                index: -1,
            })
        })
    })

    describe('events with remote data source', () => {
        beforeEach(() => {
            logic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testList',
                listGroupType: TaxonomicFilterGroupType.Events,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                showNumericalPropsOnly: false,
            })
            logic.mount()
        })

        it('calls loadRemoteItems on mount', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    remoteItems: partial({
                        results: partial([partial({ name: 'event1' })]),
                    }),
                })
        })

        it('can set the index', async () => {
            await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
            expectLogic(logic).toMatchValues({ index: 0, remoteItems: partial({ count: 156 }) })
            expectLogic(logic, () => logic.actions.setIndex(1)).toMatchValues({
                remoteItems: partial({ count: 156 }),
                index: 1,
            })
        })

        it('setting search query filters events', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('event')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'event',
                    remoteItems: partial({
                        count: 3,
                        results: partial([partial({ name: 'event1' })]),
                    }),
                })
        })

        it('setting search query loads remote items', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('event')
            })
                .toDispatchActions([
                    'setSearchQuery',
                    'loadRemoteItems',
                    'loadRemoteItemsSuccess',
                    'infiniteListResultsReceived',
                ])
                .toFinishAllListeners()
                .toMatchValues({
                    searchQuery: 'event',
                    remoteItems: partial({
                        count: 3,
                        results: partial([partial({ name: 'event1' })]),
                    }),
                    remoteItemsLoading: false,
                })
        })

        it('selects the selected item', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadRemoteItemsSuccess'])
                .toMatchValues({ selectedItem: partial({ name: 'All events', value: null }) })

            await expectLogic(logic, () => {
                logic.actions.moveDown()
                logic.actions.selectSelected()
            }).toDispatchActions([
                logic.actionCreators.selectSelected(),
                ({ type, payload }) =>
                    type === logic.actionTypes.selectItem &&
                    payload.group.type === TaxonomicFilterGroupType.Events &&
                    payload.value === 'event1' &&
                    payload.item.name === 'event1',
            ])
        })
        describe('events with local and remote data sources', () => {
            it('can set the index up and down as a circular list', async () => {
                await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
                expectLogic(logic).toMatchValues({
                    index: 0,
                    remoteItems: partial({ count: 156 }),
                    localItems: partial({ count: 1 }),
                    items: partial({ count: 157 }),
                })
                expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 156 })
                expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 155 })
                expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 156 })
                expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 0 })
                expectLogic(logic, () => logic.actions.moveDown()).toMatchValues({ index: 1 })
                expectLogic(logic, () => logic.actions.moveUp()).toMatchValues({ index: 0 })
            })

            it('joins the local and remote lists precisely on onRowsRendered', async () => {
                await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
                await expectLogic(logic).toMatchValues({
                    index: 0,
                    remoteItems: partial({ count: 156 }),
                    localItems: partial({ count: 1 }),
                    items: partial({ count: 157 }),
                })

                await expectLogic(logic, () =>
                    logic.actions.onRowsRendered({
                        startIndex: 30,
                        stopIndex: 40,
                        overscanStartIndex: 20,
                        overscanStopIndex: 60,
                    })
                )
                    .toDispatchActions(['onRowsRendered'])
                    .toNotHaveDispatchedActions(['loadRemoteItems'])

                await expectLogic(logic, () =>
                    logic.actions.onRowsRendered({
                        startIndex: 80,
                        stopIndex: 100,
                        overscanStartIndex: 70,
                        overscanStopIndex: 120,
                    })
                )
                    .toDispatchActions(['onRowsRendered', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                    .toMatchValues({
                        remoteItems: partial({ count: 156, results: mockEventDefinitions }),
                        localItems: partial({ count: 1 }),
                        items: partial({
                            count: 157,
                            results: [{ name: 'All events', value: null }, ...mockEventDefinitions],
                        }),
                    })
            })
        })
    })

    describe('with optionsFromProp', () => {
        beforeEach(() => {
            logic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testList',
                listGroupType: TaxonomicFilterGroupType.Wildcards,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                showNumericalPropsOnly: false,
                optionsFromProp: {
                    wildcard: [{ name: 'first' }, { name: 'second' }],
                },
            })
            logic.mount()
        })

        it('doesnt call loadRemoteItems on mount, loads results locally', async () => {
            await expectLogic(logic)
                .toDispatchActions([])
                .toMatchValues({
                    results: partial([partial({ name: 'first' }), partial({ name: 'second' })]),
                })
        })
    })

    describe('expandable list of event properties', () => {
        beforeEach(() => {
            logic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testList',
                listGroupType: TaxonomicFilterGroupType.EventProperties,
                eventNames: ['$pageview'],
                taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
                showNumericalPropsOnly: false,
            })
            logic.mount()
        })

        it('setting search query filters events', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('browser')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: true,
                    isExpanded: false,
                    isExpandableButtonSelected: false,
                    totalResultCount: 1,
                    totalExtraCount: 1,
                    totalListCount: 2,
                    expandedCount: 2,
                    remoteItems: partial({
                        count: 1,
                        expandedCount: 2,
                        results: partial([partial({ name: '$browser', is_seen_on_filtered_events: true })]),
                    }),
                })

            await expectLogic(logic, () => {
                logic.actions.expand()
            })
                .toDispatchActions(['expand', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: false,
                    isExpanded: true,
                    isExpandableButtonSelected: false,
                    totalResultCount: 2,
                    totalExtraCount: 0,
                    totalListCount: 2,
                    expandedCount: 0,
                    remoteItems: partial({
                        count: 2,
                        expandedCount: undefined,
                        results: partial([
                            partial({ name: '$browser', is_seen_on_filtered_events: true }),
                            partial({ name: 'browser_no_dollar_not_on_event', is_seen_on_filtered_events: false }),
                        ]),
                    }),
                })

            // remains extended after extending once
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('bro')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'bro',
                    isExpandable: false,
                    isExpanded: true,
                    isExpandableButtonSelected: false,
                    totalResultCount: 2,
                    totalExtraCount: 0,
                    totalListCount: 2,
                    expandedCount: 0,
                    remoteItems: partial({
                        count: 2,
                        expandedCount: undefined,
                        results: partial([
                            partial({ name: '$browser', is_seen_on_filtered_events: true }),
                            partial({ name: 'browser_no_dollar_not_on_event', is_seen_on_filtered_events: false }),
                        ]),
                    }),
                })
        })

        it('moving up selects expansion button', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('browser')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: true,
                    isExpanded: false,
                    isExpandableButtonSelected: false,
                    totalResultCount: 1,
                    totalExtraCount: 1,
                    totalListCount: 2,
                    expandedCount: 2,
                    index: 0,
                    remoteItems: partial({
                        count: 1,
                        expandedCount: 2,
                        results: partial([partial({ name: '$browser', is_seen_on_filtered_events: true })]),
                    }),
                })

            await expectLogic(logic, () => {
                logic.actions.moveUp()
            }).toMatchValues({ index: 1, isExpandableButtonSelected: true })

            await expectLogic(logic, () => {
                logic.actions.selectSelected()
            })
                .toDispatchActions(['selectSelected', 'expand', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    searchQuery: 'browser',
                    isExpandable: false,
                    isExpanded: true,
                    isExpandableButtonSelected: false,
                    totalResultCount: 2,
                    totalExtraCount: 0,
                    totalListCount: 2,
                    expandedCount: 0,
                    remoteItems: partial({
                        count: 2,
                        expandedCount: undefined,
                        results: partial([
                            partial({ name: '$browser', is_seen_on_filtered_events: true }),
                            partial({ name: 'browser_no_dollar_not_on_event', is_seen_on_filtered_events: false }),
                        ]),
                    }),
                })
        })
    })

    it('searches autocapture elements using posthog property', async () => {
        const logicWithProps = infiniteListLogic({
            taxonomicFilterLogicKey: 'test-element-list',
            listGroupType: TaxonomicFilterGroupType.Elements,
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Elements],
            showNumericalPropsOnly: false,
        })
        logicWithProps.mount()

        await expectLogic(logicWithProps, () => logicWithProps.actions.setSearchQuery('css')).toMatchValues({
            localItems: { count: 1, results: [{ name: 'selector' }], searchQuery: 'css', originalQuery: undefined },
        })
    })

    it('swaps in query when url is sent', async () => {
        const logicWithProps = infiniteListLogic({
            taxonomicFilterLogicKey: 'test-e-prop',
            listGroupType: TaxonomicFilterGroupType.EventProperties,
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            showNumericalPropsOnly: false,
        })
        logicWithProps.mount()

        await expectLogic(logicWithProps, () =>
            logicWithProps.actions.setSearchQuery('http://localhost:8010/project/1/replay/playlists')
        ).toMatchValues({
            swappedInQuery: '$current_url',
        })
    })

    it('swaps in query when email is sent', async () => {
        const logicWithProps = infiniteListLogic({
            taxonomicFilterLogicKey: 'test-e-prop',
            listGroupType: TaxonomicFilterGroupType.PersonProperties,
            taxonomicGroupTypes: [TaxonomicFilterGroupType.PersonProperties],
            showNumericalPropsOnly: false,
        })
        logicWithProps.mount()

        await expectLogic(logicWithProps, () =>
            logicWithProps.actions.setSearchQuery('test@example.com')
        ).toMatchValues({
            swappedInQuery: 'email',
        })
    })
})
