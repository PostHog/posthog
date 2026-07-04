import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'
import posthog from 'posthog-js'

import {
    hasRecentContext,
    recentTaxonomicFiltersLogic,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockEventPropertyDefinitions } from '~/test/mocks'
import { AppContext, PropertyDefinition, PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

import { clearApiCacheForTesting, infiniteListLogic } from './infiniteListLogic'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { hasPinnedContext, taxonomicFilterPinnedPropertiesLogic } from './taxonomicFilterPinnedPropertiesLogic'

window.POSTHOG_APP_CONTEXT = {
    current_team: { id: MOCK_TEAM_ID },
    current_project: { id: MOCK_TEAM_ID },
} as unknown as AppContext

describe('infiniteListLogic', () => {
    let logic: ReturnType<typeof infiniteListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': ({ request }) => {
                    const url = new URL(request.url)
                    const search = url.searchParams.get('search')
                    const limit = Number(url.searchParams.get('limit'))
                    const offset = Number(url.searchParams.get('offset'))
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
                '/api/projects/:team/property_definitions': ({ request }) => {
                    const url = new URL(request.url)
                    const search = url.searchParams.get('search')
                    let results = search
                        ? mockEventPropertyDefinitions.filter((e) => e.name.includes(search))
                        : mockEventPropertyDefinitions
                    if (url.searchParams.has('filter_by_event_names')) {
                        const isEventProperty = url.searchParams.get('filter_by_event_names') === 'true'
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
        clearApiCacheForTesting()
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

        it('stamps the remote load duration so callers can report search latency', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadRemoteItemsSuccess'])
                .toMatchValues({
                    remoteItems: partial({ loadDurationMs: expect.any(Number) }),
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

    describe('transient empty responses are not pinned in the module cache', () => {
        let flakyLogic: ReturnType<typeof infiniteListLogic.build>
        let requestCounts: Record<string, number>

        beforeEach(() => {
            requestCounts = {}
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': ({ request }) => {
                        const url = new URL(request.url)
                        const search = url.searchParams.get('search') ?? ''
                        requestCounts[search] = (requestCounts[search] ?? 0) + 1
                        // Simulate a backend blip: the first fetch for this term comes back empty,
                        // later fetches surface the event that actually exists.
                        const results =
                            search === 'flaky_event'
                                ? requestCounts[search] === 1
                                    ? []
                                    : [{ ...mockEventDefinitions[0], name: 'flaky_event' }]
                                : mockEventDefinitions.filter((e) => e.name.includes(search))
                        return [200, { results, count: results.length }]
                    },
                },
            })
            initKeaTests()
            flakyLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'flakyList',
                listGroupType: TaxonomicFilterGroupType.Events,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                showNumericalPropsOnly: false,
            })
            flakyLogic.mount()
        })

        it('re-fetches the same query after an empty blip instead of serving a pinned blank', async () => {
            await expectLogic(flakyLogic).toDispatchActions(['loadRemoteItemsSuccess']) // initial mount

            // First search hits the blip and comes back empty.
            await expectLogic(flakyLogic, () => {
                flakyLogic.actions.setSearchQuery('flaky_event')
            })
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({ remoteItems: partial({ count: 0 }) })

            // Retrying the identical query must re-hit the backend (the empty was not cached) and
            // surface the event that exists — otherwise it would keep reading as "No results".
            await expectLogic(flakyLogic, () => {
                flakyLogic.actions.loadRemoteItems({ offset: 0, limit: 100 })
            })
                .toDispatchActions(['loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toMatchValues({
                    remoteItems: partial({ results: partial([partial({ name: 'flaky_event' })]) }),
                })
        })
    })

    describe('remote fetch failure settles the list', () => {
        it('falls back to the empty state instead of spinning forever when the fetch fails', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': () => [500, { detail: 'server error' }],
                },
            })
            initKeaTests()
            const failingLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'failingList',
                listGroupType: TaxonomicFilterGroupType.Events,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                showNumericalPropsOnly: false,
            })
            failingLogic.mount()
            await expectLogic(failingLogic, () => {
                failingLogic.actions.setSearchQuery('user_signed_up')
            })
                .toDispatchActions([
                    'setSearchQuery',
                    'loadRemoteItems',
                    'loadRemoteItemsFailure',
                    'remoteItemsFetchFailedForQuery',
                ])
                .toMatchValues({
                    showLoadingState: false,
                    showEmptyState: true,
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

    describe('listGroupType with no matching built group', () => {
        let noGroupLogic: ReturnType<typeof infiniteListLogic.build>
        // A group-analytics index with no matching group type mapping, so `group` resolves to undefined.
        const groupsListType = `${TaxonomicFilterGroupType.GroupsPrefix}_55` as TaxonomicFilterGroupType

        beforeEach(() => {
            noGroupLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'testListNoGroup',
                listGroupType: groupsListType,
                taxonomicGroupTypes: [groupsListType],
                showNumericalPropsOnly: false,
            })
            noGroupLogic.mount()
        })

        it('returns empty localItems instead of throwing', async () => {
            await expectLogic(noGroupLogic)
                .toFinishAllListeners()
                .toMatchValues({
                    group: undefined,
                    localItems: partial({ count: 0, results: [] }),
                })
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

    describe('`taxonomic filter empty result` capture', () => {
        // Every list runs the same search in parallel — without an active-tab gate, one keystroke
        // can fire 4-8 empty events from background tabs the user never sees. Pin the gate.
        const taxonomicFilterLogicKey = 'emptyResultGateTest'
        const props = {
            taxonomicFilterLogicKey,
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties],
            showNumericalPropsOnly: false,
        }

        it.each([
            {
                name: 'fires when the empty list is the active tab',
                activeTab: TaxonomicFilterGroupType.Events,
                listGroupType: TaxonomicFilterGroupType.Events,
                expectFire: true,
            },
            {
                name: 'does not fire when the empty list is a background tab',
                activeTab: TaxonomicFilterGroupType.EventProperties,
                listGroupType: TaxonomicFilterGroupType.Events,
                expectFire: false,
            },
        ])('$name', async ({ activeTab, listGroupType, expectFire }) => {
            const captureSpy = jest.spyOn(posthog, 'capture')

            const parent = taxonomicFilterLogic(props)
            parent.mount()
            parent.actions.setActiveTab(activeTab)

            const listLogic = infiniteListLogic({ ...props, listGroupType })
            listLogic.mount()

            // Tripwire: the gate reads `isActiveTab` from the parent. If anyone refactors
            // `isActiveTab` to be self-contained, this assertion catches it before the
            // empty-result expectations silently start passing for the wrong reason.
            expect(listLogic.values.isActiveTab).toBe(activeTab === listGroupType)

            await expectLogic(listLogic, () => listLogic.actions.setSearchQuery('mcp tool call'))
                .toDispatchActions(['setSearchQuery', 'loadRemoteItems', 'loadRemoteItemsSuccess'])
                .toFinishAllListeners()

            const emptyCalls = captureSpy.mock.calls.filter((c) => c[0] === 'taxonomic filter empty result')
            if (expectFire) {
                expect(emptyCalls).toHaveLength(1)
                expect(emptyCalls[0][1]).toMatchObject({
                    groupType: listGroupType,
                    searchQuery: 'mcp tool call',
                })
            } else {
                expect(emptyCalls).toHaveLength(0)
            }
        })
    })

    describe('suggested list dedupes pinned against recents', () => {
        beforeEach(() => {
            localStorage.clear()
        })

        afterEach(() => {
            localStorage.clear()
        })

        const seedRecentAndPins = (): void => {
            const recentLogic = recentTaxonomicFiltersLogic.build()
            recentLogic.mount()
            recentLogic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.EventProperties,
                groupName: 'Event properties',
                value: '$current_url',
                item: { name: '$current_url' },
            })
            const pinnedLogic = taxonomicFilterPinnedPropertiesLogic.build()
            pinnedLogic.mount()
            pinnedLogic.actions.togglePin(
                TaxonomicFilterGroupType.EventProperties,
                'Event properties',
                '$current_url',
                {
                    name: '$current_url',
                }
            )
            pinnedLogic.actions.togglePin(TaxonomicFilterGroupType.EventProperties, 'Event properties', '$browser', {
                name: '$browser',
            })
            // Guards against default-pin seeding turning the first togglePin into an
            // unpin, which would make the dedupe assertions pass vacuously.
            expect(pinnedLogic.values.pinnedFilters.map((f) => f.value)).toEqual(['$current_url', '$browser'])
        }

        const mountSuggestedList = (): ReturnType<typeof infiniteListLogic.build> => {
            const listLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'recents-pinned-dedupe-test',
                listGroupType: TaxonomicFilterGroupType.SuggestedFilters,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.SuggestedFilters,
                ],
                showNumericalPropsOnly: false,
            })
            listLogic.mount()
            return listLogic
        }

        const pinnedValues = (results: unknown[]): unknown[] =>
            results.filter((item) => hasPinnedContext(item)).map((item) => item._pinnedContext.value)

        it.each([
            { description: 'in the idle prefix', searchQuery: '', expectedPinned: ['$browser'] },
            { description: 'in search matches', searchQuery: 'current', expectedPinned: [] },
        ])(
            'shows an item that is both recent and pinned once, under recents: $description',
            async ({ searchQuery, expectedPinned }) => {
                seedRecentAndPins()
                const listLogic = mountSuggestedList()

                if (searchQuery) {
                    listLogic.actions.setSearchQuery(searchQuery)
                    await expectLogic(listLogic).toDispatchActions(['setSearchQuery'])
                }

                const results = listLogic.values.items.results
                expect(pinnedValues(results)).toEqual(expectedPinned)
                expect(
                    results.filter(
                        (item) => hasRecentContext(item) && item._recentContext.sourceValue === '$current_url'
                    )
                ).toHaveLength(1)
            }
        )
    })

    describe('contextFilteredRecentItems', () => {
        // Generic wrapper around hasRecentContext so .filter() preserves the input type
        // (the production type guard uses `unknown` which TS can't narrow through Array.filter).
        const onlyWithRecentContext = <T>(
            item: T
        ): item is T & {
            _recentContext: { sourceGroupType: TaxonomicFilterGroupType; propertyFilter?: { value?: any } }
        } => hasRecentContext(item)

        // Recent cohort filters can carry any operator the user previously chose elsewhere
        // (insights, recordings, etc). Feature flag release conditions intentionally hide
        // the operator dropdown for cohorts (only `in` is supported), so a non-`in` recent
        // must not surface there — otherwise the picker would offer an option the
        // surrounding UI is hiding. Hosts express this via excludedOperators.
        const recentCohortIn = {
            name: 'Power Users',
            _recentContext: {
                sourceGroupType: TaxonomicFilterGroupType.Cohorts,
                sourceGroupName: 'Cohorts',
                propertyFilter: {
                    type: PropertyFilterType.Cohort,
                    key: 'id',
                    value: 1,
                    operator: PropertyOperator.In,
                    cohort_name: 'Power Users',
                },
            },
        }
        const recentCohortNotIn = {
            name: 'Trial Users',
            _recentContext: {
                sourceGroupType: TaxonomicFilterGroupType.Cohorts,
                sourceGroupName: 'Cohorts',
                propertyFilter: {
                    type: PropertyFilterType.Cohort,
                    key: 'id',
                    value: 2,
                    operator: PropertyOperator.NotIn,
                    cohort_name: 'Trial Users',
                },
            },
        }
        const recentEventProperty = {
            name: '$browser',
            _recentContext: {
                sourceGroupType: TaxonomicFilterGroupType.EventProperties,
                sourceGroupName: 'Event properties',
                propertyFilter: {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                },
            },
        }

        const seedRecents = (items: Record<string, any>[]): void => {
            const recentLogic = recentTaxonomicFiltersLogic.build()
            recentLogic.mount()
            for (const item of items) {
                recentLogic.actions.recordRecentFilter({
                    groupType: item._recentContext.sourceGroupType,
                    groupName: item._recentContext.sourceGroupName,
                    value: item._recentContext.propertyFilter.value,
                    item: { name: item.name },
                    propertyFilter: item._recentContext.propertyFilter,
                })
            }
        }

        it('hides recents whose operator is excluded for their source group', () => {
            seedRecents([recentCohortIn, recentCohortNotIn, recentEventProperty])

            const listLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'flag-recents-test',
                listGroupType: TaxonomicFilterGroupType.RecentFilters,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.RecentFilters,
                ],
                showNumericalPropsOnly: false,
                excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
            })
            listLogic.mount()

            const filtered = listLogic.values.contextFilteredRecentItems
            const cohortValues = filtered
                .filter(onlyWithRecentContext)
                .filter(
                    (i) =>
                        i._recentContext.sourceGroupType === TaxonomicFilterGroupType.Cohorts &&
                        i._recentContext.propertyFilter
                )
                .map((i) => i._recentContext.propertyFilter?.value)
            expect(cohortValues).toEqual([1])
            expect(filtered.some((i) => 'name' in i && i.name === '$browser')).toBe(true)
        })

        it('surfaces a bare key alongside each complete recent in value mode', () => {
            seedRecents([recentEventProperty])

            const listLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'recents-bare-key-test',
                listGroupType: TaxonomicFilterGroupType.RecentFilters,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.RecentFilters],
                showNumericalPropsOnly: false,
            })
            listLogic.mount()

            const items = listLogic.values.contextFilteredRecentItems.filter(onlyWithRecentContext)
            expect(items).toHaveLength(2)
            expect(items[0]._recentContext.propertyFilter).toBeUndefined()
            expect(items[1]._recentContext.propertyFilter).not.toBeUndefined()
        })

        it('keeps cohort recents whose operator is undefined even when excludedOperators is set', () => {
            const recentCohortNoOperator = {
                name: 'Static Users',
                _recentContext: {
                    sourceGroupType: TaxonomicFilterGroupType.Cohorts,
                    sourceGroupName: 'Cohorts',
                    propertyFilter: {
                        type: PropertyFilterType.Cohort,
                        key: 'id',
                        value: 3,
                        operator: undefined,
                        cohort_name: 'Static Users',
                    },
                },
            }
            seedRecents([recentCohortIn, recentCohortNoOperator, recentCohortNotIn])

            const listLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'flag-recents-no-op-test',
                listGroupType: TaxonomicFilterGroupType.RecentFilters,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.RecentFilters],
                showNumericalPropsOnly: false,
                excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
            })
            listLogic.mount()

            const cohortValues = listLogic.values.contextFilteredRecentItems
                .filter(onlyWithRecentContext)
                .filter((i) => i._recentContext.sourceGroupType === TaxonomicFilterGroupType.Cohorts)
                .map((i) => i._recentContext.propertyFilter?.value)
            // The undefined-operator recent stays (1 + 3); the explicit NotIn (2) is hidden.
            expect(cohortValues).toEqual(expect.arrayContaining([1, 3]))
            expect(cohortValues).not.toContain(2)
        })

        it('keeps all recents when excludedOperators is not set', () => {
            seedRecents([recentCohortIn, recentCohortNotIn])

            const listLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'insight-recents-test',
                listGroupType: TaxonomicFilterGroupType.RecentFilters,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Cohorts, TaxonomicFilterGroupType.RecentFilters],
                showNumericalPropsOnly: false,
            })
            listLogic.mount()

            const cohortValues = listLogic.values.contextFilteredRecentItems
                .filter(onlyWithRecentContext)
                .filter((i) => i._recentContext.sourceGroupType === TaxonomicFilterGroupType.Cohorts)
                .map((i) => i._recentContext.propertyFilter?.value)
            expect(cohortValues).toEqual(expect.arrayContaining([1, 2]))
        })

        it('preserves sourceValue on recent Persons items so the row resolves the correct distinct_id', () => {
            // Persons items are stored stripped ({name, id?}) — distinct_ids is not persisted.
            // The fix in InfiniteListRow falls back to _recentContext.sourceValue instead of
            // calling Persons.getValue (which would return undefined). This test asserts that
            // sourceValue is recorded correctly at storage time so the fallback has something to use.
            const recentLogic = recentTaxonomicFiltersLogic.build()
            recentLogic.mount()
            recentLogic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.Persons,
                groupName: 'Persons',
                value: 'user-distinct-id',
                item: { name: 'Jane Doe' },
            })

            const listLogic = infiniteListLogic({
                taxonomicFilterLogicKey: 'persons-recents-test',
                listGroupType: TaxonomicFilterGroupType.RecentFilters,
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Persons, TaxonomicFilterGroupType.RecentFilters],
                showNumericalPropsOnly: false,
            })
            listLogic.mount()

            const personItems = listLogic.values.contextFilteredRecentItems
                .filter(onlyWithRecentContext)
                .filter((i) => i._recentContext.sourceGroupType === TaxonomicFilterGroupType.Persons)

            expect(personItems).toHaveLength(1)
            expect((personItems[0] as any)._recentContext.sourceValue).toBe('user-distinct-id')
        })
    })
})
