import { ReactNode } from 'react'

import { IconExternal, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSelectOptions,
    LemonSkeleton,
    LemonTag,
    LemonTagType,
} from '@posthog/lemon-ui'

import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'

import { IntegrationType } from '~/types'

interface AlertNotificationDestinationIconAction {
    kind: 'icon'
    url: string
    tooltip: string
    targetBlank?: boolean
}

interface AlertNotificationDestinationButtonAction {
    kind: 'button'
    label: string
    url?: string
    disabledReason?: string
    dataAttr?: string
}

export interface AlertNotificationDestinationView {
    key: string
    title: string
    detail?: string | null
    tags?: { label: string; type?: LemonTagType }[]
    viewAction?: AlertNotificationDestinationIconAction | AlertNotificationDestinationButtonAction
    onDelete: () => void
}

export interface PendingAlertNotificationDestinationView {
    key: string
    label: string
    status: string
    onRemove: () => void
}

export interface AlertNotificationUrlInput {
    placeholder: string
    helpText?: ReactNode
}

interface AlertNotificationDestinationEditorProps<NotificationType extends string> {
    description?: ReactNode
    destinations: {
        showExisting: boolean
        existingLoading: boolean
        existing: AlertNotificationDestinationView[]
        pending: PendingAlertNotificationDestinationView[]
    }
    notificationType: {
        options: LemonSelectOptions<NotificationType>
        value: NotificationType
        onChange: (type: NotificationType) => void
    }
    slack: {
        notificationType: NotificationType
        integration?: IntegrationType
        channelValue: string | null
        onChannelValueChange: (value: string | null) => void
    }
    url?: {
        input: AlertNotificationUrlInput
        value: string
        onChange: (value: string) => void
    }
    add: {
        onClick: () => void
        disabledReason?: string
    }
}

function DestinationViewAction({
    action,
}: {
    action: AlertNotificationDestinationView['viewAction']
}): JSX.Element | null {
    if (!action) {
        return null
    }

    switch (action.kind) {
        case 'icon':
            return (
                <LemonButton
                    icon={<IconExternal />}
                    size="xsmall"
                    to={action.url}
                    targetBlank={action.targetBlank}
                    hideExternalLinkIcon
                    tooltip={action.tooltip}
                />
            )
        case 'button':
            return (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    to={action.url}
                    disabledReason={action.disabledReason}
                    data-attr={action.dataAttr}
                >
                    {action.label}
                </LemonButton>
            )
        default: {
            const exhaustiveCheck: never = action
            return exhaustiveCheck
        }
    }
}

function ExistingDestinations({
    loading,
    destinations,
}: {
    loading: boolean
    destinations: AlertNotificationDestinationView[]
}): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-8" repeat={2} />
    }

    if (destinations.length === 0) {
        return null
    }

    return (
        <div className="space-y-2">
            {destinations.map((destination) => (
                <div key={destination.key} className="flex items-center justify-between border rounded p-2 gap-2">
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium truncate">{destination.title}</span>
                            {destination.tags?.map((tag) => (
                                <LemonTag key={tag.label} type={tag.type} size="small">
                                    {tag.label}
                                </LemonTag>
                            ))}
                        </div>
                        {destination.detail ? (
                            <span className="text-xs text-muted-alt truncate block">{destination.detail}</span>
                        ) : null}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                        <DestinationViewAction action={destination.viewAction} />
                        <LemonButton
                            icon={<IconTrash />}
                            size="xsmall"
                            status="danger"
                            onClick={destination.onDelete}
                            tooltip="Delete notification"
                        />
                    </div>
                </div>
            ))}
        </div>
    )
}

function PendingDestinations({
    destinations,
}: {
    destinations: PendingAlertNotificationDestinationView[]
}): JSX.Element | null {
    if (destinations.length === 0) {
        return null
    }

    return (
        <div className="space-y-2">
            {destinations.map((destination) => (
                <div key={destination.key} className="flex items-center justify-between border rounded p-2 gap-2">
                    <span className="text-sm min-w-0 truncate flex flex-col">
                        {destination.label}
                        <span className="text-muted-alt">{destination.status}</span>
                    </span>
                    <LemonButton
                        icon={<IconTrash />}
                        size="xsmall"
                        status="danger"
                        onClick={destination.onRemove}
                        tooltip="Remove notification"
                    />
                </div>
            ))}
        </div>
    )
}

export function AlertNotificationDestinationEditor<NotificationType extends string>({
    description,
    destinations,
    notificationType,
    slack,
    url,
    add,
}: AlertNotificationDestinationEditorProps<NotificationType>): JSX.Element {
    let slackDestinationInput: JSX.Element | null = null
    if (notificationType.value === slack.notificationType) {
        if (slack.integration) {
            slackDestinationInput = (
                <SlackChannelPicker
                    value={slack.channelValue ?? undefined}
                    onChange={slack.onChannelValueChange}
                    integration={slack.integration}
                />
            )
        } else {
            slackDestinationInput = <SlackNotConfiguredBanner />
        }
    }

    return (
        <div className="space-y-4">
            {description ? <p className="text-xs text-muted-alt m-0">{description}</p> : null}

            {destinations.showExisting ? (
                <ExistingDestinations loading={destinations.existingLoading} destinations={destinations.existing} />
            ) : null}

            <PendingDestinations destinations={destinations.pending} />

            <div className="space-y-3 border rounded p-3">
                <LemonSelect
                    fullWidth
                    options={notificationType.options}
                    value={notificationType.value}
                    onChange={notificationType.onChange}
                />

                {slackDestinationInput}

                {url ? (
                    <div className="space-y-1">
                        <LemonInput
                            placeholder={url.input.placeholder}
                            value={url.value}
                            onChange={url.onChange}
                            fullWidth
                        />
                        {url.input.helpText ? <p className="text-xs text-muted-alt m-0">{url.input.helpText}</p> : null}
                    </div>
                ) : null}

                <LemonButton type="secondary" size="small" onClick={add.onClick} disabledReason={add.disabledReason}>
                    Add notification
                </LemonButton>
            </div>
        </div>
    )
}
