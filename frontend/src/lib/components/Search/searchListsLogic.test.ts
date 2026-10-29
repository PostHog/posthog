import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { terminalDockLogic } from 'scenes/terminal/terminalDockLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { searchListsLogic } from './searchListsLogic'
import { filterSearchItems } from './utils'

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
        const matches = filterSearchItems(logic.values.miscItems, query)

        expect(matches.find((item) => item.id === 'misc-my-tickets')?.href).toBe(urls.myTickets())
    })

    it('shows only the Inbox Scouts destination', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true })

        expect(
            logic.values.productsItems
                .filter((item) => item.displayName === 'Scouts')
                .map((item) => ({ href: item.href, parentName: item.parentName }))
        ).toEqual([{ href: urls.inbox('scouts'), parentName: 'Self-driving inbox' }])
    })

    it.each([false, true])('gates the command-menu terminal toggle when enabled=%s', (enabled) => {
        logic.unmount()
        logic = searchListsLogic({ commandPalette: true })
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
})
