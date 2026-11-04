import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

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
        <Item data-quill variant="outline" tone="info">
            <ItemContent>
                <ItemDescription>
                    Looking for the inspector, network waterfall or linked issues? They are under Debug now.
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button
                    variant="outline"
                    data-attr="player-debug-hint-open"
                    onClick={() => {
                        posthog.capture('session recording mode changed', { mode: 'debug', source: 'hint' })
                        setDebugMode(true)
                        setTab(SessionRecordingSidebarTab.INSPECTOR)
                    }}
                >
                    Open Debug
                </Button>
                <Button size="icon" aria-label="Dismiss" onClick={dismissDebugHint}>
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
