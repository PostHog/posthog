import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { openJumpToTimestampModal } from 'lib/components/DateFilter/openJumpToTimestampModal'
import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { shortcutLogic } from 'lib/components/Shortcuts/shortcutLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { openCHQueriesDebugModal } from 'lib/components/Shortcuts/utils/DebugCHQueries'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { SidePanelTab } from '~/types'

import { navigation3000Logic } from './navigation-3000/navigationLogic'
import { sidePanelStateLogic } from './navigation-3000/sidepanel/sidePanelStateLogic'
import { themeLogic } from './navigation-3000/themeLogic'
import { sceneLayoutLogic } from './scenes/sceneLayoutLogic'

export function GlobalShortcuts(): null {
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { shortcutMenuOpen } = useValues(shortcutLogic)
    const { scenePanelIsPresent } = useValues(sceneLayoutLogic)
    const { setShortcutMenuOpen } = useActions(shortcutLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const { toggleCommand } = useActions(commandLogic)
    const { toggleHelpMenu } = useActions(helpMenuLogic)
    const { toggleAccountMenu, toggleProjectSwitcher, toggleOrgSwitcher } = useActions(newAccountMenuLogic)
    const { openSuperpowers } = useActions(superpowersLogic)
    const { toggleTheme } = useActions(themeLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)

    // Open Info tab if scene has panel content, otherwise default to PostHog AI
    const defaultTab = scenePanelIsPresent ? SidePanelTab.Info : SidePanelTab.Max

    useShortcut({
        name: 'Search',
        keybind: [keyBinds.search],
        intent: 'Search',
        interaction: 'function',
        callback: () => {
            toggleCommand()
        },
        priority: 10,
    })

    useShortcut({
        name: 'ToggleShortcutMenu',
        keybind: [keyBinds.toggleShortcutMenu, keyBinds.toggleShortcutMenuFallback],
        intent: 'Toggle shortcut menu',
        interaction: 'function',
        callback: () => setShortcutMenuOpen(!shortcutMenuOpen),
    })

    useShortcut({
        name: 'DebugClickhouseQueries',
        keybind: [['command', 'option', 'tab']],
        intent: 'Debug clickhouse queries',
        interaction: 'function',
        callback: openCHQueriesDebugModal,
        disabled: !superpowersEnabled,
    })

    useShortcut({
        name: 'Superpowers',
        keybind: [['command', 'shift', 'p']],
        intent: 'Open superpowers panel',
        interaction: 'function',
        callback: openSuperpowers,
        disabled: !superpowersEnabled,
    })

    useShortcut({
        name: 'ZenMode',
        keybind: [keyBinds.zenMode],
        intent: 'Toggle zen mode',
        interaction: 'function',
        callback: () => toggleZenMode('shortcut'),
    })

    useShortcut({
        name: 'SQLEditor',
        keybind: [keyBinds.sqlEditor],
        intent: 'Open SQL editor',
        interaction: 'function',
        callback: () => {
            if (removeProjectIdIfPresent(router.values.location.pathname) !== urls.sqlEditor()) {
                router.actions.push(urls.sqlEditor())
            }
        },
    })

    useShortcut({
        name: 'toggle-context-panel',
        keybind: [keyBinds.toggleRightNav],
        intent: 'Toggle context panel',
        interaction: 'function',
        callback: () => {
            if (sidePanelOpen) {
                closeSidePanel()
            } else {
                openSidePanel(defaultTab)
            }
        },
    })

    useShortcut({
        name: 'toggle-help-menu',
        keybind: [keyBinds.helpMenu],
        intent: 'Toggle help menu',
        interaction: 'function',
        callback: () => toggleHelpMenu(),
    })

    useShortcut({
        name: 'toggle-new-account-menu',
        keybind: [keyBinds.newAccountMenu],
        intent: 'Toggle new account menu',
        interaction: 'function',
        callback: () => toggleAccountMenu(),
    })

    useShortcut({
        name: 'toggle-project-switcher',
        keybind: [keyBinds.projectSwitcher],
        intent: 'Toggle project switcher',
        interaction: 'function',
        callback: () => toggleProjectSwitcher(),
    })

    useShortcut({
        name: 'toggle-org-switcher',
        keybind: [keyBinds.orgSwitcher],
        intent: 'Toggle organization switcher',
        interaction: 'function',
        callback: () => toggleOrgSwitcher(),
    })

    useShortcut({
        name: 'toggle-theme',
        keybind: [keyBinds.theme],
        intent: 'Toggle theme (dark / light)',
        interaction: 'function',
        callback: () => toggleTheme(),
    })

    useShortcut({
        name: 'jump-to-timestamp',
        keybind: [keyBinds.jumpToTimestamp],
        intent: 'Jump to timestamp',
        interaction: 'function',
        callback: openJumpToTimestampModal,
    })

    return null
}
