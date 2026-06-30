import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { composeTicketLogic } from './composeTicketLogic'

interface ComposeTicketButtonProps {
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
    distinctId?: string
    email?: string
    iconOnly?: boolean
    onCompose?: () => void
}

export function ComposeTicketButton({
    size = 'small',
    type = 'primary',
    distinctId,
    email,
    iconOnly,
    onCompose,
}: ComposeTicketButtonProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openComposeModal } = useActions(composeTicketLogic)
    const [showDisabledPopover, setShowDisabledPopover] = useState(false)
    const conversationsEnabled = !!currentTeam?.conversations_enabled

    if (!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_CREATE_TICKET]) {
        return null
    }

    return (
        <>
            <Popover
                visible={showDisabledPopover}
                onClickOutside={() => setShowDisabledPopover(false)}
                overlay={
                    <div className="p-3 max-w-xs flex flex-col gap-2">
                        <p className="m-0 text-sm">
                            Conversations are not enabled for this project. Enable them in settings to start writing to
                            customers.
                        </p>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => {
                                setShowDisabledPopover(false)
                                router.actions.push(urls.supportSettings())
                            }}
                            fullWidth
                            center
                        >
                            Go to settings
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton
                    type={type}
                    size={size}
                    icon={<IconLetter />}
                    tooltip={iconOnly ? 'New ticket' : undefined}
                    onClick={() => {
                        if (conversationsEnabled) {
                            openComposeModal({ distinctId, email })
                            onCompose?.()
                        } else {
                            setShowDisabledPopover(true)
                        }
                    }}
                    data-attr="compose-ticket-button"
                >
                    {iconOnly ? null : 'New ticket'}
                </LemonButton>
            </Popover>
        </>
    )
}
