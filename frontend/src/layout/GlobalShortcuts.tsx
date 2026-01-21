import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { appShortcutLogic } from 'lib/components/AppShortcuts/appShortcutLogic'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { openCHQueriesDebugModal } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigation3000Logic } from './navigation-3000/navigationLogic'

export function GlobalShortcuts(): null {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { activeTabId } = useValues(sceneLogic)
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const isNewSearchUx = useFeatureFlag('NEW_SEARCH_UX')
    const { toggleCommand } = useActions(commandLogic)

    const showDebugQueries =
        user?.is_staff || user?.is_impersonated || preflight?.is_debug || preflight?.instance_preferences?.debug_queries

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
        disabled: !showDebugQueries,
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

    return null
}
