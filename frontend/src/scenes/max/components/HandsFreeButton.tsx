import { useActions, useValues } from 'kea'

import { IconMicrophone } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { handsFreeLogic } from '../handsFreeLogic'

interface HandsFreeButtonProps {
    panelId?: string
}

export function HandsFreeButton({ panelId }: HandsFreeButtonProps): JSX.Element | null {
    const flagEnabled = useFeatureFlag('MAX_HANDS_FREE')
    const { status, canUseHandsFree } = useValues(handsFreeLogic({ panelId }))
    const { toggleHandsFree } = useActions(handsFreeLogic({ panelId }))

    if (!flagEnabled || !canUseHandsFree || status !== 'off') {
        return null
    }

    return (
        <Shortcut name="maxHandsFree" keybind={[keyBinds.maxHandsFree]} intent="Enter hands-free" interaction="click">
            <LemonButton
                data-attr="max-hands-free-toggle"
                size="small"
                type="tertiary"
                icon={<IconMicrophone />}
                onClick={toggleHandsFree}
                tooltip="Enter hands-free"
                aria-label="Enter hands-free"
            />
        </Shortcut>
    )
}
