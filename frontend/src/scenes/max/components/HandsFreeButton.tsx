import { useActions, useValues } from 'kea'

import { IconMicrophone } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { handsFreeLogic } from '../handsFreeLogic'

interface HandsFreeButtonProps {
    tabId?: string
    sidePanel?: boolean
}

export function HandsFreeButton({ tabId, sidePanel }: HandsFreeButtonProps): JSX.Element | null {
    const flagEnabled = useFeatureFlag('MAX_HANDS_FREE')
    const { status, canUseHandsFree } = useValues(handsFreeLogic({ tabId, sidePanel }))
    const { toggleHandsFree } = useActions(handsFreeLogic({ tabId, sidePanel }))

    if (!flagEnabled || !canUseHandsFree || status !== 'off') {
        return null
    }

    return (
        <AppShortcut
            name="maxHandsFree"
            keybind={[keyBinds.maxHandsFree]}
            intent="Enter hands-free"
            interaction="click"
        >
            <LemonButton
                data-attr="max-hands-free-toggle"
                size="small"
                type="tertiary"
                icon={<IconMicrophone />}
                onClick={toggleHandsFree}
                tooltip="Enter hands-free"
                aria-label="Enter hands-free"
            />
        </AppShortcut>
    )
}
