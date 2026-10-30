import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner } from '@posthog/lemon-ui'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'

import { SessionRecordingSidebarTab } from '~/types'

export function DebugModeBanner(): JSX.Element | null {
    const { debugMode, debugHintDismissed, watchLayoutOffered } = useValues(playerSettingsLogic)
    const { setDebugMode, dismissDebugHint } = useActions(playerSettingsLogic)
    const { setTab } = useActions(playerSidebarLogic)

    if (debugMode || debugHintDismissed || !watchLayoutOffered) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            onClose={dismissDebugHint}
            action={{
                children: 'Open Debug',
                'data-attr': 'player-debug-hint-open',
                onClick: () => {
                    posthog.capture('session recording mode changed', { mode: 'debug', source: 'hint' })
                    setDebugMode(true)
                    setTab(SessionRecordingSidebarTab.INSPECTOR)
                },
            }}
        >
            Looking for the inspector, network waterfall or linked issues? They are under Debug now.
        </LemonBanner>
    )
}
