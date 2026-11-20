import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { ShellFrame } from './components/ShellFrame'
import { sessionsAvailabilityLogic } from './sessionsAvailabilityLogic'
import { SHELL_TABS, shellHref, shellLinkParams, shellLocationForSceneKey, shellTabPath } from './shellNavigation'

function useTabShortcut(
    position: 1 | 2 | 3 | 4,
    linkParams: Record<string, unknown>,
    hasSessions: boolean | null
): void {
    const { push } = useActions(router)
    const tab = SHELL_TABS[position - 1]

    useShortcut({
        name: `AIObservabilityTab${position}`,
        keybind: [keyBinds[`tab${position}`]],
        intent: `Go to ${tab.label}`,
        interaction: 'function',
        callback: () => push(shellHref(shellTabPath(tab, hasSessions), linkParams)),
        scope: Scene.AIObservability,
    })
}

export function ShellHost({ children }: { children: React.ReactNode }): JSX.Element {
    const { sceneKey } = useValues(sceneLogic)
    const { searchParams } = useValues(router)
    const { push } = useActions(router)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { hasSessions } = useValues(sessionsAvailabilityLogic)
    const linkParams = shellLinkParams(searchParams)

    useTabShortcut(1, linkParams, hasSessions)
    useTabShortcut(2, linkParams, hasSessions)
    useTabShortcut(3, linkParams, hasSessions)
    useTabShortcut(4, linkParams, hasSessions)

    return (
        <ShellFrame
            location={shellLocationForSceneKey(sceneKey)}
            linkParams={linkParams}
            hasSessions={hasSessions}
            todayRailNav={todayRailNav}
            onScopeChange={(scope) => push(shellHref(scope.path, linkParams))}
        >
            {children}
        </ShellFrame>
    )
}
