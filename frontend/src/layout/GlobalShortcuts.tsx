import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { appShortcutLogic } from 'lib/components/AppShortcuts/appShortcutLogic'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { openCHQueriesDebugModal } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from './navigation-3000/navigationLogic'

export function GlobalShortcuts(): null {
    const { activeTabId } = useValues(sceneLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)

    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const { toggleCommand } = useActions(commandLogic)
    const { toggleHelpMenu } = useActions(helpMenuLogic)
    const { toggleAccountMenu } = useActions(newAccountMenuLogic)
    const { openSuperpowers } = useActions(superpowersLogic)

    const isNewSearchUx = useFeatureFlag('NEW_SEARCH_UX')

    useAppShortcut({
        name: 'Search',
        keybind: [keyBinds.search],
        intent: 'Search',
        interaction: 'function',
        callback: () => {
            if (isNewSearchUx) {
                toggleCommand()
            } else {
                if (removeProjectIdIfPresent(router.values.location.pathname) === urls.newTab()) {
                    const mountedLogic = activeTabId ? newTabSceneLogic.findMounted({ tabId: activeTabId }) : null
                    if (mountedLogic) {
                        setTimeout(() => mountedLogic.actions.triggerSearchPulse(), 100)
                    }
                } else {
                    router.actions.push(urls.newTab())
                }
            }
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
        name: 'toggle-new-account-menu',
        keybind: [keyBinds.newAccountMenu],
        intent: 'Toggle new account menu',
        interaction: 'function',
        callback: () => toggleAccountMenu(),
    })

    return null
}
