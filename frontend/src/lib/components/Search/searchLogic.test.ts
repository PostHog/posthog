import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { terminalDockLogic } from 'scenes/terminal/terminalDockLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { recentItemsModel } from '~/models/recentItemsModel'
import { initKeaTests } from '~/test/init'

import { searchLogic } from './searchLogic'
import { SEARCH_TAB_CATEGORY, filterSearchItems } from './utils'

/** Poll until a condition holds. The searches settle in no fixed order, so an ordered
 *  `toDispatchActions` list would wait on an action that had already gone past. */
const waitFor = async (condition: () => boolean, timeoutMs = 4000): Promise<void> => {
    const deadline = Date.now() + timeoutMs
    while (!condition()) {
        if (Date.now() > deadline) {
            throw new Error('Timed out waiting for the other searches to settle')
        }
        await new Promise((resolve) => setTimeout(resolve, 25))
    }
}

describe('searchLogic', () => {
    let logic: ReturnType<typeof searchLogic.build>
    let personSearchCalls: { clientQueryId?: string; signal?: AbortSignal }[]
    let cancelledQueryIds: string[]
    let personListMock: jest.SpyInstance

    const neverResolvingPersonSearch = (): void => {
        personListMock.mockImplementation((params, options) => {
            personSearchCalls.push({ clientQueryId: params?.client_query_id, signal: options?.signal })
            return new Promise((_resolve, reject) => {
                options?.signal?.addEventListener('abort', () => {
                    reject(Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' }))
                })
            })
        })
    }

    const searchOnceProductsLoad = async (search: string): Promise<void> => {
        await expectLogic(recentItemsModel).toDispatchActions(['loadSceneLogViewsSuccess'])
        logic.actions.setSearch(search)
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/search/': { results: [], counts: {} },
                '/api/projects/:team_id/file_system/': { results: [], count: 0 },
                '/api/projects/:team_id/file_system/log_view/': [],
                '/api/projects/:team_id/conversations/tickets/': { results: [], count: 0 },
            },
        })
        initKeaTests()

        personSearchCalls = []
        cancelledQueryIds = []
        personListMock = jest.spyOn(api.persons, 'list')
        jest.spyOn(api, 'cancelQuery').mockImplementation(async (clientQueryId: string) => {
            cancelledQueryIds.push(clientQueryId)
        })

        logic = searchLogic({ logicKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each([false, true])('gates the command-menu terminal toggle when enabled=%s', (enabled) => {
        logic.unmount()
        logic = searchLogic({ logicKey: 'command' })
        logic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: enabled })

        const toggle = logic.values.miscItems.find((item) => item.id === 'misc-toggle-terminal')
        expect(!!toggle).toBe(enabled)
        expect(terminalDockLogic.values.dockOpen).toBe(false)
        if (toggle) {
            toggle.onSelect?.()
            expect(terminalDockLogic.values.dockOpen).toBe(true)
            toggle.onSelect?.()
            expect(terminalDockLogic.values.dockOpen).toBe(false)
            toggle.onSelect?.()
            featureFlagLogic.actions.setFeatureFlags([], {})
            expect(terminalDockLogic.values.dockOpen).toBe(false)
            expect(logic.values.miscItems.some((item) => item.id === 'misc-toggle-terminal')).toBe(false)
        }
        featureFlagLogic.actions.setFeatureFlags([], {})
        terminalDockLogic.actions.toggleTerminal()
        expect(terminalDockLogic.values.dockOpen).toBe(false)
    })

    it.each([
        ['off', false, 'Model preferences', false],
        ['on', true, 'Agent preferences', true],
    ])(
        'shows one copy of a section gated on a flag and its negation, with the flag %s',
        (_state, flagOn, expectedName, expectsGatedKeyword) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: flagOn })
            const settings = [
                {
                    id: 'task-agent-my-preference',
                    hasTitle: true,
                    titleString: 'My default model',
                    descriptionString: null,
                },
                {
                    id: 'task-comments-slack-dm',
                    hasTitle: true,
                    titleString: 'Gated setting',
                    descriptionString: null,
                    keywords: ['zebra'],
                    flag: 'TODAY_RAIL_NAV' as const,
                },
            ]
            logic.actions.setSettingsSections([
                {
                    id: 'environment-task-agents',
                    level: 'environment',
                    titleString: 'Agent preferences',
                    flag: 'TODAY_RAIL_NAV',
                    settings,
                },
                {
                    id: 'environment-task-agents',
                    level: 'environment',
                    titleString: 'Model preferences',
                    flag: '!TODAY_RAIL_NAV',
                    settings,
                },
            ])

            const items = logic.values.settingsItems.filter((item) => item.id === 'settings-project-task-agents')
            expect(items.map((item) => item.displayName)).toEqual([expectedName])
            expect(items[0].name.includes('zebra')).toBe(expectsGatedKeyword)
        }
    )

    it('aborts and cancels the in-flight person search when the term is cleared', async () => {
        neverResolvingPersonSearch()

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])
        expect(personSearchCalls).toHaveLength(1)
        const { clientQueryId, signal } = personSearchCalls[0]
        expect(clientQueryId).toBeTruthy()
        expect(signal?.aborted).toBe(false)

        await expectLogic(logic, () => logic.actions.setSearch('')).toDispatchActions([
            'loadPersonSearchResultsFailure',
        ])
        expect(signal?.aborted).toBe(true)
        expect(cancelledQueryIds).toEqual([clientQueryId])
        expect(logic.values.personSearchResultsLoading).toBe(false)
    })

    it('cancels the previous person search on a new term without clearing the loading state', async () => {
        neverResolvingPersonSearch()

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])
        await expectLogic(logic, () => logic.actions.setSearch('alice b')).toDispatchActions([
            'loadPersonSearchResults',
        ])

        expect(personSearchCalls).toHaveLength(2)
        expect(personSearchCalls[0].signal?.aborted).toBe(true)
        expect(personSearchCalls[1].signal?.aborted).toBe(false)
        expect(cancelledQueryIds).toEqual([personSearchCalls[0].clientQueryId])

        // The superseded run must not settle the loader the newer run now owns.
        await expectLogic(logic).toNotHaveDispatchedActions(['loadPersonSearchResultsFailure'])
        expect(logic.values.personSearchResultsLoading).toBe(true)
    })

    it.each([
        ['materialized views', 'dataManagementItems', 'Models'],
        ['batch exports', 'dataManagementItems', 'Destinations Batch exports'],
        ['insights', 'productsItems', 'Product analytics'],
        ['semantic layer', 'productsItems', 'Data catalog'],
        ['Semantic Layer', 'productsItems', 'Data catalog'],
        ['semanticlayer', 'productsItems', 'Data catalog'],
        ['semantic-layer', 'productsItems', 'Data catalog'],
        ['featureflags', 'productsItems', 'Feature flags'],
        ['Feature Flags', 'productsItems', 'Feature flags'],
        ['segments', 'peopleItems', 'Cohorts'],
    ] as const)('finds an item by a manifest search keyword: %s', (search, selector, itemName) => {
        const matches = filterSearchItems(logic.values[selector], search)
        expect(matches.map((item) => item.name)).toContain(itemName)
    })

    it.each([
        ['data quality', true, true],
        ['dataquality', true, true],
        ['Data-Quality', true, true],
        ['models data quality', true, true],
        ['data quality', false, false],
        ['', true, false],
    ])(
        'lists the Models data quality tab for search %j with the flag on=%s: %s',
        async (search, flagEnabled, listed) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DATA_QUALITY_CHECKS]: flagEnabled })
            await searchOnceProductsLoad(search)

            const rows = logic.values.allCategories.flatMap((category) =>
                category.items.filter((item) => item.href === urls.models('data-quality'))
            )
            expect(rows.map((row) => ({ displayName: row.displayName, parentName: row.parentName }))).toEqual(
                listed ? [{ displayName: 'Data quality', parentName: 'Models' }] : []
            )
        }
    )

    it.each([
        ['batch exports', [], '/data-management/destinations?tab=batch'],
        ['metrics sql', [], '/metrics?activeTab=sql'],
        ['dashboards cross-project', [FEATURE_FLAGS.CROSS_PROJECT_DASHBOARDS], '/dashboard?tab=cross-project'],
        ['tracing sql', [FEATURE_FLAGS.TRACING, FEATURE_FLAGS.TRACING_SCENE_TABS], '/tracing?tab=sql'],
        ['reusable widgets', [FEATURE_FLAGS.NOTEBOOK_GENERATED_WIDGETS], '/notebooks?tab=widgets'],
        ['replay vision usage', [], '/replay-vision?tab=usage'],
    ])('links the tab row found by %j with flags %j to %s', async (search, flags, href) => {
        featureFlagLogic.actions.setFeatureFlags([], Object.fromEntries(flags.map((flag) => [flag, true])))
        await searchOnceProductsLoad(search)

        const tabs = logic.values.allCategories.find((category) => category.key === SEARCH_TAB_CATEGORY)
        expect(tabs?.items.map((item) => item.href)).toContain(href)
    })

    it('does not list every tab row for "ab", which only resembles the group name', async () => {
        await searchOnceProductsLoad('ab')

        const rows = logic.values.allCategories.flatMap((category) => category.items)
        expect(rows.some((item) => item.category === SEARCH_TAB_CATEGORY)).toBe(true)
        expect(rows.map((item) => item.href)).not.toContain('/metrics?activeTab=sql')
    })

    it('lists Error tracking first in Products for "errors"', async () => {
        await searchOnceProductsLoad('errors')

        const products = logic.values.allCategories.find((category) => category.key === 'tools')
        expect(products?.items[0]?.name).toBe('Error tracking')
    })

    it('lists the Tabs group above Settings', async () => {
        logic.actions.setSettingsSections([
            {
                id: 'environment-web-analytics',
                level: 'environment',
                titleString: 'Web vitals',
                settings: [
                    {
                        id: 'web-vitals-autocapture',
                        hasTitle: true,
                        titleString: 'Web vitals',
                        descriptionString: null,
                    },
                ],
            },
        ])
        await searchOnceProductsLoad('web vitals')

        const keys = logic.values.allCategories.map((category) => category.key)
        expect(keys).toContain('settings')
        expect(keys.indexOf(SEARCH_TAB_CATEGORY)).toBeGreaterThan(-1)
        expect(keys.indexOf(SEARCH_TAB_CATEGORY)).toBeLessThan(keys.indexOf('settings'))
    })

    it.each([
        [false, 'Live events'],
        [true, 'Activity'],
    ])('leads "live events" with LIVESTREAM_HOGQL=%s to %s', (liveEventsRetired, expectedDisplayName) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.LIVESTREAM_HOGQL]: liveEventsRetired })

        const matches = filterSearchItems(logic.values.productsItems, 'live events')
        expect(matches.map((item) => item.displayName)).toEqual([expectedDisplayName])
    })

    it('lists Persons above the Tabs group for "users"', async () => {
        await searchOnceProductsLoad('users')

        const keys = logic.values.allCategories.map((category) => category.key)
        const people = logic.values.allCategories.find((category) => category.key === 'people')
        expect(people?.items[0]?.name).toBe('Persons')
        expect(keys.indexOf(SEARCH_TAB_CATEGORY)).toBeGreaterThan(keys.indexOf('people'))
    })

    it.each([
        ['newflag', 'New Feature flag'],
        ['new flag', 'New Feature flag'],
        ['New Feature Flag', 'New Feature flag'],
        ['newfeatureflag', 'New Feature flag'],
        ['create flag', 'New Feature flag'],
        ['new site app', 'New Web script'],
        ['new site_app', 'New Web script'],
    ])('puts the right item first in the create category for %j', (search, expectedFirst) => {
        logic.actions.setSearch(search)

        const create = logic.values.allCategories.find((category) => category.key === 'create')
        expect(create?.items[0]?.name).toBe(expectedFirst)
    })

    it('maps matching support tickets into their own category', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': {
                    count: 1,
                    results: [
                        {
                            id: '01890a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b',
                            ticket_number: 4321,
                            status: 'on_hold',
                            email_subject: 'Invoice looks wrong',
                            last_message_text: 'We were charged twice',
                        },
                    ],
                },
            },
        })

        await expectLogic(logic, () => logic.actions.setSearch('invoice')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])

        expect(logic.values.ticketItems).toEqual([
            expect.objectContaining({
                name: '#4321 Invoice looks wrong',
                category: 'tickets',
                href: urls.supportTicketDetail(4321),
                productCategory: 'On hold',
            }),
        ])
        expect(logic.values.allCategories.find((category) => category.key === 'tickets')?.items).toHaveLength(1)
    })

    // A Slack or widget ticket has no email subject, so the first message stands in as the title.
    it('falls back to the last message when a ticket has no subject', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': {
                    count: 1,
                    results: [
                        {
                            id: '01890a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5c',
                            ticket_number: 77,
                            status: 'open',
                            email_subject: null,
                            last_message_text: 'Session replay is not recording',
                        },
                    ],
                },
            },
        })

        await expectLogic(logic, () => logic.actions.setSearch('replay')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])

        expect(logic.values.ticketItems[0].name).toBe('#77 Session replay is not recording')
    })

    // Free-text ticket search scans message content, so the palette must not send one per
    // keystroke while a query is still a letter or two long.
    it('does not search tickets until the query is long enough', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': {
                    count: 1,
                    results: [{ id: 'ticket-uuid', ticket_number: 12, status: 'open', email_subject: 'Billing' }],
                },
            },
        })

        await expectLogic(logic, () => logic.actions.setSearch('bi')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])
        expect(logic.values.ticketItems).toEqual([])

        await expectLogic(logic, () => logic.actions.setSearch('bill')).toDispatchActions([
            'loadTicketSearchResultsSuccess',
        ])
        expect(logic.values.ticketItems).toHaveLength(1)
    })

    // Ticket search scans message content, so it is the slowest query in the palette and the one
    // most likely to still be in flight when the others settle. Leaving it out of `isSearching`
    // let the status line read "No results found" over a search that had not finished.
    it('still counts as searching while only tickets are in flight', async () => {
        personListMock.mockResolvedValue({ results: [] })
        // The mock team has group types, so the groups query would otherwise stay in flight and
        // hold `isSearching` true on its own, hiding the very thing under test.
        jest.spyOn(api.groups, 'listClickhouse').mockResolvedValue({ results: [], columns: [] } as any)
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/tickets/': () => new Promise(() => {}),
            },
        })

        logic.actions.setSearch('billing')

        // Every other search has to have settled, or `isSearching` would be true for a reason
        // other than the one under test. They finish in no fixed order, so wait on the values.
        await waitFor(
            () =>
                !logic.values.searchPending &&
                !logic.values.searchedRecentsLoading &&
                !logic.values.unifiedSearchResultsLoading &&
                !logic.values.groupSearchResultsLoading &&
                !logic.values.personSearchResultsLoading &&
                !logic.values.playlistSearchResultsLoading
        )

        expect(logic.values.ticketSearchResultsLoading).toBe(true)
        expect(logic.values.isSearching).toBe(true)
    })

    it('does not cancel a person search that already returned', async () => {
        personListMock.mockResolvedValue({ results: [] })

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions([
            'loadPersonSearchResultsSuccess',
        ])
        await expectLogic(logic, () => logic.actions.setSearch('')).toFinishAllListeners()

        expect(cancelledQueryIds).toEqual([])
    })
})
