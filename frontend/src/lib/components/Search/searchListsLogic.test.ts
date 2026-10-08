import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { terminalDockLogic } from 'scenes/terminal/terminalDockLogic'

import { initKeaTests } from '~/test/init'

import { searchListsLogic } from './searchListsLogic'

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
