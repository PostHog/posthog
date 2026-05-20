import './HandsFreeButton.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconMicrophone } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { handsFreeLogic } from '../handsFreeLogic'

interface HandsFreeButtonProps {
    tabId: string
}

export function HandsFreeButton({ tabId }: HandsFreeButtonProps): JSX.Element | null {
    const flagEnabled = useFeatureFlag('MAX_HANDS_FREE')
    const { status, canUseHandsFree } = useValues(handsFreeLogic({ tabId }))
    const { toggleHandsFree } = useActions(handsFreeLogic({ tabId }))

    if (!flagEnabled || !canUseHandsFree) {
        return null
    }
    // When hands-free is active, the big mic inside HandsFreeSurface is the exit affordance.
    // The composer-corner button only renders for the "enter hands-free" path.
    if (status !== 'off') {
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
                data-status={status}
                size="small"
                type="tertiary"
                icon={<IconMicrophone className={clsx('hands-free-mic-icon')} />}
                onClick={toggleHandsFree}
                tooltip="Enter hands-free"
                aria-label="Enter hands-free"
            />
        </AppShortcut>
    )
}
