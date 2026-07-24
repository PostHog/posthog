import { ReactNode } from 'react'

import { IconExternal, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonBanner,
    LemonInput,
    LemonSelect,
    LemonSelectOptions,
    LemonSkeleton,
    LemonTag,
    LemonTagType,
} from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
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
    title: ReactNode
    detail?: ReactNode
    tags?: { label: string; type?: LemonTagType }[]
    viewAction?: AlertNotificationDestinationIconAction | AlertNotificationDestinationButtonAction
    onDelete: () => void
}

export interface PendingAlertNotificationDestinationView {
    key: string
    title: ReactNode
    detail?: ReactNode
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
        integrationsLoading: boolean
        integrationsFailed: boolean
        onRetryIntegrations: () => void
        integrations?: IntegrationType[]
        integration?: IntegrationType
        onIntegrationChange?: (integrationId: number | null) => void
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
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium truncate">{destination.title}</span>
                            <LemonTag type="warning" size="small">
                                Pending
                            </LemonTag>
                        </div>
                        {destination.detail ? (
                            <span className="text-xs text-muted-alt truncate block">{destination.detail}</span>
                        ) : null}
                    </div>
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
    const addDestinationButton = (
        <LemonButton
            type="primary"
            size="small"
            onClick={add.onClick}
            disabledReason={add.disabledReason}
            className="shrink-0"
        >
            Add
        </LemonButton>
    )
    const addDestinationButtonIsInline = notificationType.value === slack.notificationType || Boolean(url)

    let slackDestinationInput: JSX.Element | null = null
    if (notificationType.value === slack.notificationType) {
        if (slack.integrationsLoading || slack.integrations === undefined) {
            slackDestinationInput = <LemonSkeleton className="h-10" />
        } else if (slack.integrationsFailed) {
            slackDestinationInput = (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: slack.onRetryIntegrations,
                    }}
                >
                    Couldn't load Slack workspaces.
                </LemonBanner>
            )
        } else if (slack.integration) {
            slackDestinationInput = (
                <div className="space-y-3">
                    {(slack.integrations?.length ?? 0) > 1 ? (
                        <fieldset className="space-y-1">
                            <legend className="text-sm font-medium">Slack workspace</legend>
                            <IntegrationChoice
                                integration="slack"
                                value={slack.integration.id}
                                onChange={(integrationId) => {
                                    if (integrationId !== slack.integration?.id) {
                                        slack.onIntegrationChange?.(integrationId)
                                    }
                                }}
                                allowClear={false}
                            />
                        </fieldset>
                    ) : null}
                    <fieldset className="space-y-1">
                        <legend className="text-sm font-medium">Channel</legend>
                        <div className="flex flex-col sm:flex-row items-start gap-2">
                            <div className="flex-1 min-w-0 w-full">
                                <SlackChannelPicker
                                    value={slack.channelValue ?? undefined}
                                    onChange={slack.onChannelValueChange}
                                    integration={slack.integration}
                                />
                            </div>
                            {addDestinationButton}
                        </div>
                    </fieldset>
                </div>
            )
        } else {
            slackDestinationInput = <SlackNotConfiguredBanner type="warning" className="max-w-4xl" />
        }
    }

    const hasDestinations =
        (destinations.showExisting && (destinations.existingLoading || destinations.existing.length > 0)) ||
        destinations.pending.length > 0

    return (
        <div className="flex flex-col gap-4" data-prevent-wizard-submit>
            {description ? <p className="text-xs text-muted-alt m-0">{description}</p> : null}

            {destinations.showExisting ? (
                <ExistingDestinations loading={destinations.existingLoading} destinations={destinations.existing} />
            ) : null}

            <PendingDestinations destinations={destinations.pending} />

            {hasDestinations ? <hr className="border-border m-0" /> : null}

            <div className="space-y-3 max-w-xl">
                <LemonSelect
                    fullWidth
                    options={notificationType.options}
                    value={notificationType.value}
                    onChange={notificationType.onChange}
                />

                {slackDestinationInput}

                {url ? (
                    <div className="space-y-1">
                        <div className="flex flex-col sm:flex-row items-start gap-2">
                            <LemonInput
                                placeholder={url.input.placeholder}
                                value={url.value}
                                onChange={url.onChange}
                                onPressEnter={(event) => {
                                    if (event.nativeEvent.isComposing) {
                                        event.stopPropagation()
                                        return
                                    }
                                    event.preventDefault()
                                    event.stopPropagation()
                                    if (!add.disabledReason) {
                                        add.onClick()
                                    }
                                }}
                                fullWidth
                            />
                            {addDestinationButton}
                        </div>
                        {url.input.helpText ? <p className="text-xs text-muted-alt m-0">{url.input.helpText}</p> : null}
                    </div>
                ) : null}

                {!addDestinationButtonIsInline ? addDestinationButton : null}
            </div>
        </div>
    )
}
