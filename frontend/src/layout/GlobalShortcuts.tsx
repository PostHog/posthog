import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { appShortcutLogic } from 'lib/components/AppShortcuts/appShortcutLogic'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { openCHQueriesDebugModal } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { healthMenuLogic } from 'lib/components/HealthMenu/healthMenuLogic'
import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from './navigation-3000/navigationLogic'
import { themeLogic } from './navigation-3000/themeLogic'

export function GlobalShortcuts(): null {
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)

    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const { toggleCommand } = useActions(commandLogic)
    const { toggleHelpMenu } = useActions(helpMenuLogic)
    const { toggleAccountMenu, toggleProjectSwitcher, toggleOrgSwitcher } = useActions(newAccountMenuLogic)
    const { openSuperpowers } = useActions(superpowersLogic)
    const { toggleHealthMenu } = useActions(healthMenuLogic)
    const { toggleTheme } = useActions(themeLogic)

    useAppShortcut({
        name: 'Search',
        keybind: [keyBinds.search],
        intent: 'Search',
        interaction: 'function',
        callback: () => {
            toggleCommand()
        },
        priority: 10,
    })

    useAppShortcut({
        name: 'ToggleShortcutMenu',
        keybind: [keyBinds.toggleShortcutMenu, keyBinds.toggleShortcutMenuFallback],
        intent: 'Toggle shortcut menu',
        interaction: 'function',
        callback: () => setAppShortcutMenuOpen(!appShortcutMenuOpen),
    })

    useAppShortcut({
        name: 'DebugClickhouseQueries',
        keybind: [['command', 'option', 'tab']],
        intent: 'Debug clickhouse queries',
        interaction: 'function',
        callback: openCHQueriesDebugModal,
        disabled: !superpowersEnabled,
    })

    useAppShortcut({
        name: 'Superpowers',
        keybind: [['command', 'shift', 'p']],
        intent: 'Open superpowers panel',
        interaction: 'function',
        callback: openSuperpowers,
        disabled: !superpowersEnabled,
    })

    useAppShortcut({
        name: 'ZenMode',
        keybind: [keyBinds.zenMode],
        intent: 'Toggle zen mode',
        interaction: 'function',
        callback: toggleZenMode,
    })

    useAppShortcut({
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

    useAppShortcut({
        name: 'toggle-help-menu',
        keybind: [keyBinds.helpMenu],
        intent: 'Toggle help menu',
        interaction: 'function',
        callback: () => toggleHelpMenu(),
    })

    useAppShortcut({
        name: 'toggle-health-menu',
        keybind: [keyBinds.healthMenu],
        intent: 'Toggle health menu',
        interaction: 'function',
        callback: () => toggleHealthMenu(),
    })

    useAppShortcut({
        name: 'toggle-new-account-menu',
        keybind: [keyBinds.newAccountMenu],
        intent: 'Toggle new account menu',
        interaction: 'function',
        callback: () => toggleAccountMenu(),
    })

    useAppShortcut({
        name: 'toggle-project-switcher',
        keybind: [keyBinds.projectSwitcher],
        intent: 'Toggle project switcher',
        interaction: 'function',
        callback: () => toggleProjectSwitcher(),
    })

    useAppShortcut({
        name: 'toggle-org-switcher',
        keybind: [keyBinds.orgSwitcher],
        intent: 'Toggle organization switcher',
        interaction: 'function',
        callback: () => toggleOrgSwitcher(),
    })

    useAppShortcut({
        name: 'toggle-theme',
        keybind: [keyBinds.theme],
        intent: 'Toggle theme (dark / light)',
        interaction: 'function',
        callback: () => toggleTheme(),
    })

    return null
}
