import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { appShortcutLogic } from 'lib/components/AppShortcuts/appShortcutLogic'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { openCHQueriesDebugModal } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

export function GlobalShortcuts(): null {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { activeTabId } = useValues(sceneLogic)
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)

    const showDebugQueries =
        user?.is_staff || user?.is_impersonated || preflight?.is_debug || preflight?.instance_preferences?.debug_queries

    useAppShortcut({
        name: 'Search',
        keybind: [keyBinds.search],
        intent: 'Search',
        interaction: 'function',
        callback: () => {
            if (removeProjectIdIfPresent(router.values.location.pathname) === urls.newTab()) {
                const mountedLogic = activeTabId ? newTabSceneLogic.findMounted({ tabId: activeTabId }) : null
                if (mountedLogic) {
                    setTimeout(() => mountedLogic.actions.triggerSearchPulse(), 100)
                }
            } else {
                router.actions.push(urls.newTab())
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

    return null
}
