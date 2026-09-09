import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconLetter } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    Button,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { composeTicketLogic } from './composeTicketLogic'

interface ComposeTicketButtonProps {
    size?: 'xsmall' | 'small' | 'medium'
    type?: 'primary' | 'secondary' | 'tertiary'
    distinctId?: string
    email?: string
    iconOnly?: boolean
    onCompose?: () => void
}

function lemonSizeToQuill(
    size: ComposeTicketButtonProps['size'],
    iconOnly: boolean | undefined
): 'xs' | 'sm' | 'default' | 'icon-xs' | 'icon-sm' | 'icon' {
    if (iconOnly) {
        if (size === 'xsmall') {
            return 'icon-xs'
        }
        if (size === 'small') {
            return 'icon-sm'
        }
        return 'icon'
    }
    if (size === 'xsmall') {
        return 'xs'
    }
    if (size === 'small') {
        return 'sm'
    }
    return 'default'
}

function lemonTypeToQuill(type: ComposeTicketButtonProps['type']): 'primary' | 'outline' | 'default' {
    if (type === 'primary') {
        return 'primary'
    }
    if (type === 'secondary') {
        return 'outline'
    }
    return 'default'
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

    const buttonSize = lemonSizeToQuill(size, iconOnly)
    const variant = lemonTypeToQuill(type)

    return (
        <AccessControlAction resourceType={AccessControlResourceType.Ticket} minAccessLevel={AccessControlLevel.Editor}>
            {({ disabled, disabledReason }) => {
                const trigger = (
                    <Button
                        variant={variant}
                        size={buttonSize}
                        disabled={disabled}
                        aria-label={iconOnly ? 'New ticket' : undefined}
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
                        <IconLetter />
                        {iconOnly ? null : 'New ticket'}
                    </Button>
                )

                const button =
                    disabled && disabledReason ? (
                        <Tooltip>
                            <TooltipTrigger render={trigger} />
                            <TooltipContent>{disabledReason}</TooltipContent>
                        </Tooltip>
                    ) : iconOnly ? (
                        <Tooltip>
                            <TooltipTrigger render={trigger} />
                            <TooltipContent>New ticket</TooltipContent>
                        </Tooltip>
                    ) : (
                        trigger
                    )

                return (
                    <Popover
                        open={showDisabledPopover}
                        onOpenChange={(nextOpen) => {
                            if (!nextOpen) {
                                setShowDisabledPopover(false)
                            }
                        }}
                    >
                        <PopoverTrigger render={button} />
                        <PopoverContent align="end" className="w-xs">
                            <div className="flex flex-col gap-2">
                                <Text size="sm">
                                    Support is not enabled for this project. Enable it in settings to start writing to
                                    customers.
                                </Text>
                                <Button
                                    variant="primary"
                                    size="sm"
                                    className="w-full"
                                    onClick={() => {
                                        setShowDisabledPopover(false)
                                        router.actions.push(urls.supportSettings())
                                    }}
                                >
                                    Go to settings
                                </Button>
                            </div>
                        </PopoverContent>
                    </Popover>
                )
            }}
        </AccessControlAction>
    )
}
