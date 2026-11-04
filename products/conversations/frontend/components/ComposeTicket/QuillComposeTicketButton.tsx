import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonButtonProps } from '@posthog/lemon-ui'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { quillButtonVariant } from 'lib/lemon-ui/LemonButton/quillButtonVariant'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { composeTicketLogic } from './composeTicketLogic'

interface QuillComposeTicketButtonProps {
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
    distinctId?: string
    email?: string
    iconOnly?: boolean
    onCompose?: () => void
}

export function QuillComposeTicketButton({
    size = 'small',
    type = 'primary',
    distinctId,
    email,
    iconOnly,
    onCompose,
}: QuillComposeTicketButtonProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { openComposeModal } = useActions(composeTicketLogic)
    const [showDisabledPopover, setShowDisabledPopover] = useState(false)
    const conversationsEnabled = !!currentTeam?.conversations_enabled

    return (
        <Popover
            open={showDisabledPopover}
            // The trigger only opens the popover when support is off; otherwise its click opens the compose modal.
            onOpenChange={(open) => setShowDisabledPopover(open && !conversationsEnabled)}
        >
            <AccessControlAction
                resourceType={AccessControlResourceType.Ticket}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <PopoverTrigger
                    render={
                        <Button
                            variant={quillButtonVariant(type)}
                            // Icon-only instances sit in dense rows (person popovers), so they keep the smaller size.
                            size={iconOnly ? (size === 'xsmall' || size === 'xxsmall' ? 'icon-xs' : 'icon') : undefined}
                            aria-label={iconOnly ? 'New ticket' : undefined}
                            tooltip={iconOnly ? 'New ticket' : undefined}
                            onClick={() => {
                                if (conversationsEnabled) {
                                    openComposeModal({ distinctId, email })
                                    onCompose?.()
                                }
                            }}
                            data-attr="compose-ticket-button"
                        />
                    }
                >
                    <IconLetter />
                    {iconOnly ? null : 'New ticket'}
                </PopoverTrigger>
            </AccessControlAction>
            <PopoverContent className="max-w-xs flex flex-col gap-2">
                <p className="m-0 text-xs">
                    Support is not enabled for this project. Enable it in settings to start writing to customers.
                </p>
                <Button
                    variant="primary"
                    onClick={() => {
                        setShowDisabledPopover(false)
                        router.actions.push(urls.supportSettings())
                    }}
                >
                    Go to settings
                </Button>
            </PopoverContent>
        </Popover>
    )
}
