import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockEventPropertyDefinitions } from '~/test/mocks'
import { AppContext, PropertyDefinition, PropertyType } from '~/types'

import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

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

        it('toggles pinned rows and keeps the highlighted index in sync', async () => {
            await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data

            await expectLogic(logic, () => logic.actions.togglePinnedRow(1)).toMatchValues({
                index: 1,
                pinnedRowIndex: 1,
            })

            await expectLogic(logic, () => logic.actions.togglePinnedRow(1)).toMatchValues({
                index: 1,
                pinnedRowIndex: null,
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

        describe('"All events" visibility', () => {
            it('shows "All events" when the search query is empty', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadRemoteItemsSuccess'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        localItems: partial({
                            count: 1,
                            results: [{ name: 'All events', value: null }],
                        }),
                    })
            })

            it.each([
                ['All e', 'prefix'],
                ['all events', 'lowercase'],
                ['ALL EVENTS', 'uppercase'],
                ['All Events', 'title case'],
                ['events', 'suffix only'],
                ['ll ev', 'mid substring'],
            ])('shows "All events" when the search query is %s (%s)', async (query) => {
                await expectLogic(logic, () => {
                    logic.actions.setSearchQuery(query)
                })
                    .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        localItems: partial({
                            count: 1,
                            results: [{ name: 'All events', value: null }],
                        }),
                    })
            })

            it.each([
                ['mcp tool call', 'long unrelated query'],
                ['foobar', 'short unrelated query'],
                ['xyz', 'no overlap'],
                ['$pageview', 'real event name'],
            ])('hides "All events" when the search query is %s (%s)', async (query) => {
                await expectLogic(logic, () => {
                    logic.actions.setSearchQuery(query)
                })
                    .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        localItems: partial({
                            count: 0,
                            results: [],
                        }),
                    })
            })

            it('excludes "All events" from the combined items list for a non-matching query but keeps remote events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setSearchQuery('event')
                })
                    .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        // Remote /event_definitions mock returns 3 events whose names contain "event".
                        // "All events" also contains "event" so the meta option is kept as the first local item.
                        items: partial({
                            count: 4,
                            results: partial([{ name: 'All events', value: null }, partial({ name: 'event1' })]),
                        }),
                    })

                await expectLogic(logic, () => {
                    logic.actions.setSearchQuery('mcp tool call')
                })
                    .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        // Remote mock returns 0 matches; local "All events" is filtered out by substring match.
                        items: partial({
                            count: 0,
                            results: [],
                        }),
                    })
            })

            it('restores "All events" when the search query is cleared', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setSearchQuery('mcp tool call')
                })
                    .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        localItems: partial({ count: 0 }),
                    })

                await expectLogic(logic, () => {
                    logic.actions.setSearchQuery('')
                })
                    .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                    .toFinishAllListeners()
                    .toMatchValues({
                        localItems: partial({
                            count: 1,
                            results: [{ name: 'All events', value: null }],
                        }),
                    })
            })
        })

        it('resets pinned state when the search query changes', async () => {
            await expectLogic(logic).toDispatchActions(['loadRemoteItemsSuccess']) // wait for data
            await expectLogic(logic, () => logic.actions.togglePinnedRow(1)).toMatchValues({
                pinnedRowIndex: 1,
            })

            await expectLogic(logic, () => {
                logic.actions.setSearchQuery('event')
            })
                .toFinishAllListeners()
                .toMatchValues({
                    searchQuery: 'event',
                    pinnedRowIndex: null,
                    hasAppliedInitialPin: false,
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
                        overscanStopIndex: 60,
                    })
                )
                    .toDispatchActions(['onRowsRendered'])
                    .toNotHaveDispatchedActions(['loadRemoteItems'])

                await expectLogic(logic, () =>
                    logic.actions.onRowsRendered({
                        startIndex: 80,
                        stopIndex: 100,
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

    describe('internal events local options filtering', () => {
        // The Internal Events group has multiple local options ("All internal events" plus
        // product filter options), so substring matching needs to cover both the meta option
        // and the concrete labels.
        let internalLogic: ReturnType<typeof infiniteListLogic.build>

        beforeEach(() => {
            internalLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testListInternal',
                listGroupType: TaxonomicFilterGroupType.InternalEvents,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.InternalEvents],
                showNumericalPropsOnly: false,
            })
            internalLogic.mount()
        })

        it('shows all options when the search query is empty', async () => {
            await expectLogic(internalLogic)
                .toFinishAllListeners()
                .toMatchValues({
                    localItems: partial({
                        results: partial([partial({ name: 'All internal events' })]),
                    }),
                })
            expect(internalLogic.values.localItems.count).toBeGreaterThanOrEqual(1)
        })

        it('keeps "All internal events" when the search query matches it', async () => {
            await expectLogic(internalLogic, () => {
                internalLogic.actions.setSearchQuery('internal')
            })
                .toDispatchActions(['setSearchQuery'])
                .toFinishAllListeners()
                .toMatchValues({
                    localItems: partial({
                        results: partial([{ name: 'All internal events', value: null }]),
                    }),
                })
        })

        it('hides "All internal events" when the search query does not match any option', async () => {
            await expectLogic(internalLogic, () => {
                internalLogic.actions.setSearchQuery('mcp tool call')
            })
                .toDispatchActions(['setSearchQuery'])
                .toFinishAllListeners()
                .toMatchValues({
                    localItems: partial({
                        count: 0,
                        results: [],
                    }),
                })
        })

        it('keeps option labels when the search query matches them (case-insensitive)', async () => {
            await expectLogic(internalLogic, () => {
                internalLogic.actions.setSearchQuery('TEAM')
            })
                .toDispatchActions(['setSearchQuery'])
                .toFinishAllListeners()
            // "Team activity" is one of the default activity-log product filter options.
            const names = internalLogic.values.localItems.results.map((item: any) => item.name)
            expect(names).toContain('Team activity')
            expect(names).not.toContain('All internal events')
        })
    })

    describe('data warehouse pin lifecycle', () => {
        beforeEach(() => {
            const databaseLogic = databaseTableListLogic()
            databaseLogic.mount()
            databaseLogic.actions.loadDatabaseSuccess({
                tables: {
                    orders: {
                        id: 'orders',
                        name: 'orders',
                        type: 'data_warehouse',
                        format: 'Parquet',
                        url_pattern: '',
                        fields: {},
                    },
                    customers: {
                        id: 'customers',
                        name: 'customers',
                        type: 'data_warehouse',
                        format: 'Parquet',
                        url_pattern: '',
                        fields: {},
                    },
                },
                joins: [],
            } as any)

            dataWarehouseSettingsSceneLogic().mount()
        })

        it('reapplies the initial pin when the data warehouse tab becomes active again', async () => {
            const dataWarehouseLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'test-data-warehouse-list',
                listGroupType: TaxonomicFilterGroupType.DataWarehouse,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.DataWarehouse],
                showNumericalPropsOnly: false,
                groupType: TaxonomicFilterGroupType.DataWarehouse,
                value: 'customers',
            })
            dataWarehouseLogic.mount()

            await expectLogic(dataWarehouseLogic).toMatchValues({
                index: 1,
                pinnedRowIndex: 1,
                hasAppliedInitialPin: true,
            })

            await expectLogic(dataWarehouseLogic, () => {
                dataWarehouseLogic.actions.setActiveTab(TaxonomicFilterGroupType.Events)
            }).toMatchValues({
                pinnedRowIndex: null,
                hasAppliedInitialPin: false,
            })

            await expectLogic(dataWarehouseLogic, () => {
                dataWarehouseLogic.actions.setActiveTab(TaxonomicFilterGroupType.DataWarehouse)
            }).toMatchValues({
                index: 1,
                pinnedRowIndex: 1,
                hasAppliedInitialPin: true,
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

    it('filters local data warehouse person properties to numeric ones when requested', async () => {
        const databaseLogic = databaseTableListLogic()
        databaseLogic.mount()
        databaseLogic.actions.loadDatabaseSuccess({
            tables: {
                companies: {
                    id: 'companies',
                    name: 'companies',
                    type: 'data_warehouse',
                    format: 'Parquet',
                    url_pattern: '',
                    fields: {
                        revenue: {
                            name: 'revenue',
                            hogql_value: 'companies.revenue',
                            type: 'integer',
                            schema_valid: true,
                        },
                        name: {
                            name: 'name',
                            hogql_value: 'companies.name',
                            type: 'string',
                            schema_valid: true,
                        },
                    },
                },
            },
            joins: [],
        } as any)

        const joinsLogicInstance = joinsLogic()
        joinsLogicInstance.mount()
        joinsLogicInstance.actions.loadJoinsSuccess([
            {
                id: 'join-1',
                source_table_name: 'persons',
                joining_table_name: 'companies',
                field_name: 'company',
            },
        ])

        const logicWithProps = infiniteListLogic({
            taxonomicFilterLogicKey: 'test-data-warehouse-person-properties',
            listGroupType: TaxonomicFilterGroupType.DataWarehousePersonProperties,
            taxonomicGroupTypes: [TaxonomicFilterGroupType.DataWarehousePersonProperties],
            showNumericalPropsOnly: true,
        })
        logicWithProps.mount()

        await expectLogic(logicWithProps).toMatchValues({
            localItems: {
                count: 1,
                results: [
                    partial({ id: 'company.revenue', name: 'company: revenue', property_type: PropertyType.Numeric }),
                ],
                searchQuery: '',
            },
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
            localItems: { count: 1, results: [{ name: 'selector' }], searchQuery: 'css' },
        })
    })

    describe('keyword shortcuts', () => {
        let keySuffix = 0
        const mountEventsLogic = (enableKeywordShortcuts: boolean): ReturnType<typeof infiniteListLogic.build> => {
            // Unique key per test so kea doesn't hand us a logic instance that was already mounted
            // with a previous test's mock data.
            keySuffix += 1
            const listLogic = infiniteListLogic({
                taxonomicFilterLogicKey: `keywordShortcutsTest-${enableKeywordShortcuts}-${keySuffix}`,
                listGroupType: TaxonomicFilterGroupType.Events,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                showNumericalPropsOnly: false,
                enableKeywordShortcuts,
            })
            listLogic.mount()
            return listLogic
        }

        it('surfaces matching shortcut items when enableKeywordShortcuts is true', async () => {
            const listLogic = mountEventsLogic(true)

            await expectLogic(listLogic, () => listLogic.actions.setSearchQuery('click'))
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    keywordShortcutItems: partial([
                        partial({
                            _type: 'quick_filter',
                            name: 'Click (autocapture)',
                            filterValue: 'click',
                            eventName: '$autocapture',
                        }),
                    ]),
                })
        })

        it('places shortcuts at the TOP of the list so they are prominent and Enter picks them', async () => {
            const listLogic = mountEventsLogic(true)
            await expectLogic(listLogic).toDispatchActions(['loadRemoteItemsSuccess']).toFinishAllListeners()

            await expectLogic(listLogic, () => listLogic.actions.setSearchQuery('click'))
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toFinishAllListeners()

            // First result is the shortcut; real matches follow.
            const results = listLogic.values.items.results
            expect(results[0]).toMatchObject({ _type: 'quick_filter', filterValue: 'click' })
        })

        it('contributes shortcuts to topMatchesForQuery so they flow into the SuggestedFilters aggregate', async () => {
            const listLogic = mountEventsLogic(true)
            await expectLogic(listLogic).toDispatchActions(['loadRemoteItemsSuccess']).toFinishAllListeners()

            await expectLogic(listLogic, () => listLogic.actions.setSearchQuery('click'))
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toFinishAllListeners()

            const topMatches = listLogic.values.topMatchesForQuery
            expect(topMatches[0]).toMatchObject({ _type: 'quick_filter', filterValue: 'click' })
        })

        it('returns no shortcut items when enableKeywordShortcuts is false', async () => {
            const listLogic = mountEventsLogic(false)

            await expectLogic(listLogic, () => listLogic.actions.setSearchQuery('click'))
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    keywordShortcutItems: [],
                })
        })

        it('returns no shortcut items when the search query does not match a keyword', async () => {
            const listLogic = mountEventsLogic(true)

            await expectLogic(listLogic, () => listLogic.actions.setSearchQuery('xyzabc'))
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    keywordShortcutItems: [],
                })
        })
    })
})
