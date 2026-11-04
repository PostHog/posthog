import { buildRankedResults } from 'lib/components/CommandKSearch/commandKRankedResults'
import { strictLocalMatches } from 'lib/components/CommandKSearch/commandKRanking'
import { buildSections, emptyRemoteSlots } from 'lib/components/CommandKSearch/commandKSections'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { terminalDockLogic } from 'scenes/terminal/terminalDockLogic'
import { urls } from 'scenes/urls'

import type { Setting } from '~/scenes/settings/types'
import { initKeaTests } from '~/test/init'
import { ActivityTab } from '~/types'

import { searchListsLogic, searchListsLogicValues } from './searchListsLogic'
import { filterSearchItems } from './utils'

type DestinationList = keyof Pick<
    searchListsLogicValues,
    'productsItems' | 'dataManagementItems' | 'peopleItems' | 'healthItems'
>

const TOP_LEVEL_DESTINATIONS: [DestinationList, string, string][] = [
    ['productsItems', 'Activity', urls.activity(ActivityTab.ExploreEvents)],
    ['productsItems', 'Subscriptions', urls.subscriptions()],
    ['productsItems', 'Exports', urls.exports()],
    ['productsItems', 'Your tickets', urls.myTickets()],
    ['productsItems', 'Product analytics', urls.insights()],
    ['productsItems', 'Dashboards', urls.dashboards()],
    ['productsItems', 'Notebooks', urls.notebooks()],
    ['productsItems', 'SQL editor', urls.sqlEditor()],
    ['productsItems', 'Toolbar', urls.toolbarLaunch()],
    ['productsItems', 'Heatmaps', urls.heatmaps()],
    ['productsItems', 'Early access features', urls.earlyAccessFeatures()],
    ['productsItems', 'Endpoints', urls.endpoints()],
    ['productsItems', 'Annotations', urls.annotations()],
    ['productsItems', 'Actions', urls.actions()],
    ['productsItems', 'Destinations', urls.destinations()],
    ['productsItems', 'Transformations', urls.transformations()],
    ['productsItems', 'Models', urls.models()],
    ['dataManagementItems', 'Property definitions', urls.propertyDefinitions()],
    ['peopleItems', 'Persons', urls.persons()],
    ['peopleItems', 'Cohorts', urls.cohorts()],
    ['healthItems', 'Health', urls.health()],
    ['healthItems', 'Pipeline status', urls.pipelineStatus()],
]

describe('searchListsLogic', () => {
    let logic: ReturnType<typeof searchListsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = searchListsLogic({ commandPalette: false })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        [false, false, false],
        [true, false, true],
        [false, true, true],
        [true, true, true],
    ])('shows Data ops with DuckDB=%s and Trino=%s', (duckdb, trino, visible) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: duckdb,
            [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: trino,
        })

        expect(logic.values.productsItems.some((item) => item.id === 'product-Data warehouse')).toBe(visible)
    })

    it.each(TOP_LEVEL_DESTINATIONS)('%s includes %s', (list, name, href) => {
        const items = logic.values[list].filter((item) => !item.parentName)

        expect(items.filter((item) => item.href === href).map((item) => item.displayName)).toEqual([name])
    })

    it('lists each product destination once', () => {
        const hrefs = logic.values.productsItems.filter((item) => item.category === 'tools').map((item) => item.href)

        expect(hrefs.filter((href) => href === urls.endpoints())).toHaveLength(1)
        expect(new Set(hrefs).size).toBe(hrefs.length)
    })

    it.each([false, true])('shows Models Usage when its feature flag is enabled=%s', (enabled) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DATA_MODELING_USAGE]: enabled })

        expect(logic.values.productsItems.some((item) => item.href === urls.models('usage'))).toBe(enabled)
    })

    it.each(['support', 'tickets', 'contact support', 'help'])('finds Your tickets when searching "%s"', (query) => {
        const matches = filterSearchItems(logic.values.productsItems, query)

        expect(matches.find((item) => item.id === 'misc-my-tickets')?.href).toBe(urls.myTickets())
    })

    it('lists Alerts only as a Product analytics tab', () => {
        const lists = [
            logic.values.productsItems,
            logic.values.dataManagementItems,
            logic.values.peopleItems,
            logic.values.healthItems,
            logic.values.actionItems,
        ]

        expect(
            lists
                .flat()
                .filter((item) => item.href === urls.alerts())
                .map((item) => ({ displayName: item.displayName, parentName: item.parentName }))
        ).toEqual([{ displayName: 'Alerts', parentName: 'Product analytics' }])
    })

    it('shows only the Inbox Scouts destination', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true })

        expect(
            logic.values.productsItems
                .filter((item) => item.displayName === 'Scouts')
                .map((item) => ({ href: item.href, parentName: item.parentName }))
        ).toEqual([{ href: urls.inbox('scouts'), parentName: 'Self-driving inbox' }])
    })

    it.each([
        [false, ['Log out']],
        [true, ['Toggle terminal', 'Log out']],
    ])('lists the Actions section with the terminal enabled=%s', (enabled, names) => {
        logic.unmount()
        logic = searchListsLogic({ commandPalette: true })
        logic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: enabled })

        expect(logic.values.actionItems.map((item) => [item.displayName, item.category])).toEqual(
            names.map((name) => [name, 'actions'])
        )
        expect(filterSearchItems(logic.values.actionItems, 'log out').map((item) => item.id)).toEqual(['misc-logout'])
        const toggle = logic.values.actionItems.find((item) => item.id === 'misc-toggle-terminal')
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
            expect(logic.values.actionItems.some((item) => item.id === 'misc-toggle-terminal')).toBe(false)
        }
        featureFlagLogic.actions.setFeatureFlags([], {})
        terminalDockLogic.actions.toggleTerminal()
        expect(terminalDockLogic.values.dockOpen).toBe(false)
    })

    it.each([false, true])(
        'finds a setting through its section keyword next to a dashboard named like the search, unified ranking %s',
        (unifiedRanking) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true })
            const component = {} as JSX.Element
            logic.actions.setSettingsMap([
                {
                    id: 'environment-ai-cloud-environments',
                    level: 'environment',
                    title: 'Cloud environments',
                    flag: 'TODAY_RAIL_NAV',
                    keywords: ['desktop'],
                    settings: [
                        { id: 'ai-cloud-environments', title: 'Environments', component },
                        { id: 'ai-cloud-custom-images', title: 'Custom images', keywords: ['dependencies'], component },
                    ],
                },
            ])
            const remote = emptyRemoteSlots()
            remote.results = {
                cache: {
                    'desktop images': [
                        {
                            id: 'dashboard-1',
                            name: 'Desktop images board',
                            category: 'results',
                            record: { type: 'dashboard', ref: '1' },
                            rankKey: [-2, 0, 0, 0, -2, 0, 1, 0, 0],
                        },
                    ],
                },
            }
            const sections = buildSections({
                mode: 'search',
                context: { kind: 'text', token: null },
                suggestions: null,
                local: {
                    products: [],
                    'data-management': [],
                    people: [],
                    health: [],
                    actions: [],
                    shortcuts: [],
                    settings: logic.values.commandKSettingsItems,
                    create: [],
                    recents: [],
                    starred: [],
                },
                remote,
                remoteQueries: { results: 'desktop images' },
                localQuery: 'desktop images',
                themeItem: null,
                askAiQuestion: null,
                viewAll: null,
                stale: false,
                personsFirst: false,
                unifiedRanking,
                searchCorrection: null,
            })

            expect(
                sections.flatMap((section) => section.rows.flatMap((row) => (row.kind === 'item' ? [row.item.id] : [])))
            ).toContain('settings-project-ai-cloud-environments-ai-cloud-custom-images')
        }
    )

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

    it('keeps one row per settings section for the search list', () => {
        logic.actions.setSettingsSections([
            {
                id: 'environment-details',
                level: 'environment',
                titleString: 'General',
                settings: [
                    {
                        id: 'variables',
                        hasTitle: true,
                        titleString: 'Project token & ID',
                        descriptionString: null,
                        keywords: ['api key'],
                    },
                ],
            },
            { id: 'organization-members', level: 'organization', titleString: 'Members', settings: [] },
        ])

        expect(logic.values.settingsItems).toEqual([
            {
                id: 'settings-project-details',
                name: 'Project: General (Variables,Project token & ID,api key)',
                displayName: 'General (Project)',
                category: 'settings',
                href: urls.settings('project-details'),
                itemType: 'settings',
                record: { type: 'settings', level: 'project', sectionId: 'project-details' },
            },
            {
                id: 'settings-organization-members',
                name: 'Organization: Members ()',
                displayName: 'Members',
                category: 'settings',
                href: urls.settings('organization-members'),
                itemType: 'settings',
                record: { type: 'settings', level: 'organization', sectionId: 'organization-members' },
            },
        ])
    })

    it.each([
        ['project general', 'settings-project-details', true],
        ['2fa', 'settings-user-profile-2fa', true],
        ['rename project', 'settings-project-customization-display-name', false],
        ['desktop images', 'settings-project-ai-cloud-environments-ai-cloud-custom-images', false],
        ['password', 'settings-user-profile-change-password', true],
    ])('finds the Command K setting row %s', (query, id, ranked) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true })
        const component = {} as JSX.Element
        logic.actions.setSettingsMap([
            {
                id: 'environment-ai-cloud-environments',
                level: 'environment',
                title: 'Cloud environments',
                flag: 'TODAY_RAIL_NAV',
                keywords: ['desktop'],
                settings: [
                    { id: 'ai-cloud-environments', title: 'Environments', component },
                    { id: 'ai-cloud-custom-images', title: 'Custom images', keywords: ['dependencies'], component },
                ],
            },
            {
                id: 'environment-details',
                level: 'environment',
                title: 'General',
                settings: [{ id: 'variables', title: 'Project token & ID', component }],
            },
            {
                id: 'environment-customization',
                level: 'environment',
                title: 'Customization',
                settings: [{ id: 'display-name', title: 'Project details', keywords: ['rename'], component }],
            },
            {
                id: 'user-profile',
                level: 'user',
                title: 'Profile',
                settings: [
                    { id: '2fa', title: 'Two-factor authentication', component },
                    { id: 'change-password', title: component, keywords: ['password'], component },
                ],
            },
        ])
        const items = logic.values.commandKSettingsItems

        const fuzzy = filterSearchItems(items, query)
        expect(fuzzy.map((item) => item.id)).toContain(id)
        const strictIds = strictLocalMatches(items, query).map((item) => item.id)
        expect(ranked ? strictIds : [id]).toContain(id)
        const rankedRows = buildRankedResults({
            query,
            highlightWords: [],
            results: [],
            products: [],
            settings: strictLocalMatches(fuzzy, query),
            state: 'ready',
            scoped: false,
        }).flatMap((section) => section.rows)
        expect(
            [...fuzzy, ...rankedRows.flatMap((row) => (row.kind === 'item' ? [row.item] : []))]
                .map((item) => item.matchedSearchKeyword ?? null)
                .filter(Boolean)
        ).toEqual([])
    })

    it.each([
        ['off', false, 'Model preferences', false],
        ['on', true, 'Agent preferences', true],
    ])(
        'gives Command K one copy of a section gated on a flag and its negation, with the flag %s',
        (_state, flagOn, expectedName, expectsGatedSetting) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: flagOn })
            const settings: Setting[] = [
                { id: 'task-agent-my-preference', title: 'My default model', component: {} as JSX.Element },
                {
                    id: 'task-comments-slack-dm',
                    title: 'Gated setting',
                    component: {} as JSX.Element,
                    keywords: ['zebra'],
                    flag: 'TODAY_RAIL_NAV',
                },
            ]
            logic.actions.setSettingsMap([
                {
                    id: 'environment-task-agents',
                    level: 'environment',
                    title: 'Agent preferences',
                    flag: 'TODAY_RAIL_NAV',
                    settings,
                },
                {
                    id: 'environment-task-agents',
                    level: 'environment',
                    title: 'Model preferences',
                    flag: '!TODAY_RAIL_NAV',
                    settings,
                },
            ])

            const sections = logic.values.commandKSettingsItems.filter(
                (item) => item.id === 'settings-project-task-agents'
            )
            expect(sections.map((item) => [item.displayName, item.parentName])).toEqual([
                [expectedName, 'Project settings'],
            ])
            const gated = filterSearchItems(logic.values.commandKSettingsItems, 'zebra').map((item) => item.href)
            expect(gated).toEqual(expectsGatedSetting ? ['/settings/project-task-agents#task-comments-slack-dm'] : [])
        }
    )
})
