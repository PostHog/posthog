import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { appShortcutLogic } from 'lib/components/AppShortcuts/appShortcutLogic'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { openCHQueriesDebugModal } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { openJumpToTimestampModal } from 'lib/components/DateFilter/openJumpToTimestampModal'
import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { SidePanelTab } from '~/types'

import hesoyamSfx from 'public/hesoyam.mp3'

import { navigation3000Logic } from './navigation-3000/navigationLogic'
import { sidePanelStateLogic } from './navigation-3000/sidepanel/sidePanelStateLogic'
import { themeLogic } from './navigation-3000/themeLogic'
import { sceneLayoutLogic } from './scenes/sceneLayoutLogic'

export function GlobalShortcuts(): null {
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { appShortcutMenuOpen } = useValues(appShortcutLogic)
    const { scenePanelIsPresent } = useValues(sceneLayoutLogic)
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
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

    useAppShortcut({
        name: 'jump-to-timestamp',
        keybind: [keyBinds.jumpToTimestamp],
        intent: 'Jump to timestamp',
        interaction: 'function',
        callback: openJumpToTimestampModal,
    })

    useAppShortcut({
        name: 'Hesoyam',
        keybind: [keyBinds.hesoyam],
        intent: 'Easter egg',
        hidden: true,
        interaction: 'function',
        callback: async () => {
            try {
                await api.create('api/billing/coupons/claim', {
                    campaign_slug: 'hesoyam',
                })

                new Audio(hesoyamSfx).play().catch(() => {})

                lemonToast.success(
                    <>
                        <style>{`
                            @keyframes hesoyam-fill {
                                0% { width: 55%; }
                                100% { width: 85%; }
                            }
                            @keyframes hesoyam-bonus-pop {
                                0% { opacity: 0; transform: scale(0.5) translateY(2px); }
                                60% { opacity: 1; transform: scale(1.15) translateY(-1px); }
                                100% { opacity: 1; transform: scale(1) translateY(0); }
                            }
                        `}</style>
                        <div className="flex items-center gap-3 font-mono" style={{ minWidth: 280 }}>
                            <span className="text-xs font-bold uppercase tracking-wider opacity-90">Total respect</span>
                            <div className="flex-1 flex items-center gap-1.5">
                                <div
                                    className="h-3 rounded-sm flex-1 overflow-hidden"
                                    style={{ backgroundColor: 'rgba(255,255,255,0.15)' }}
                                >
                                    <div
                                        className="h-full rounded-sm"
                                        style={{
                                            width: '85%',
                                            background: 'linear-gradient(90deg, #4b9c4b 0%, #6bcf6b 100%)',
                                            animation: 'hesoyam-fill 0.8s ease-out',
                                        }}
                                    />
                                </div>
                                <span className="text-xs font-bold opacity-70">+</span>
                            </div>
                            <span
                                className="font-bold"
                                style={{
                                    color: '#5dde5d',
                                    fontSize: '0.8125rem',
                                    lineHeight: 1,
                                    textShadow: '0 0 8px rgba(93, 222, 93, 0.5)',
                                    animation: 'hesoyam-bonus-pop 0.5s ease-out 0.7s both',
                                }}
                            >
                                +$5
                            </span>
                        </div>
                    </>
                )
            } catch (error: any) {
                // Stay quiet on errors that aren't "already redeemed" so we
                // don't advertise the easter egg's existence.
                const detail = (error?.detail ?? error?.data?.detail ?? '').toString().toLowerCase()
                if (detail.includes('already claimed')) {
                    lemonToast.info('Nice try. You already used this cheat code.')
                }
            }
        },
    })

    return null
}
