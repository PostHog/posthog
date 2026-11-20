import { KeyboardEvent } from 'react'

import { IconExternal, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    FieldLegend,
    FieldSet,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonSelectOptionLeaf, LemonSelectOptions, isLemonSelectSection } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { quillBadgeVariant } from 'lib/lemon-ui/LemonTag/quillBadgeVariant'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import {
    ALERT_PAGERDUTY_REGION_OPTIONS,
    ALERT_PAGERDUTY_SEVERITY_OPTIONS,
    AlertNotificationDestinationEditorProps,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
    addDestinationOnEnter,
} from './AlertNotificationDestinationEditor'

function leafOptions<T>(options: LemonSelectOptions<T>): LemonSelectOptionLeaf<T>[] {
    return options
        .flatMap((option) => (isLemonSelectSection(option) ? option.options : [option]))
        .filter((option): option is LemonSelectOptionLeaf<T> => 'value' in option)
}

function DestinationTag({
    label,
    type,
    tooltip,
}: NonNullable<AlertNotificationDestinationView['tags']>[number]): JSX.Element {
    const variant = quillBadgeVariant(type)

    if (!tooltip) {
        return <Badge variant={variant}>{label}</Badge>
    }

    return (
        <Tooltip>
            <TooltipTrigger render={<Badge variant={variant} tabIndex={0} />}>{label}</TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
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
                <Button
                    size="icon-sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={action.url} target={action.targetBlank ? '_blank' : undefined} />}
                    aria-label={action.tooltip}
                    tooltip={action.tooltip}
                >
                    <IconExternal />
                </Button>
            )
        case 'button':
            return action.url && !action.disabledReason ? (
                <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={action.url} />}
                    data-attr={action.dataAttr}
                >
                    {action.label}
                </Button>
            ) : (
                <Button variant="outline" size="sm" disabledReason={action.disabledReason} data-attr={action.dataAttr}>
                    {action.label}
                </Button>
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
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
            </div>
        )
    }

    if (destinations.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {destinations.map((destination) => (
                <Item key={destination.key} variant="outline" size="sm">
                    <ItemContent className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                            <ItemTitle className="truncate">{destination.title}</ItemTitle>
                            {destination.tags?.map((tag) => (
                                <DestinationTag key={tag.label} {...tag} />
                            ))}
                        </div>
                        {destination.detail ? (
                            <ItemDescription className="truncate">{destination.detail}</ItemDescription>
                        ) : null}
                    </ItemContent>
                    <ItemActions className="flex-wrap">
                        {destination.messageAction ? (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={destination.messageAction.onClick}
                                loading={destination.messageAction.loading}
                                tooltip={destination.messageAction.tooltip}
                                data-attr={destination.messageAction.dataAttr}
                            >
                                {destination.messageAction.label}
                            </Button>
                        ) : null}
                        <DestinationViewAction action={destination.viewAction} />
                        <Button
                            variant="destructive-outline"
                            size="icon-sm"
                            onClick={destination.onDelete}
                            loading={destination.deleting}
                            disabledReason={destination.deleting ? 'Deleting notification.' : undefined}
                            aria-label="Delete notification"
                            tooltip="Delete notification"
                        >
                            <IconTrash />
                        </Button>
                    </ItemActions>
                </Item>
            ))}
        </div>
    )
}

function PendingDestinations({
    destinations,
    tooltip = 'Save this alert to add this destination.',
}: {
    destinations: PendingAlertNotificationDestinationView[]
    tooltip?: string
}): JSX.Element | null {
    if (destinations.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {destinations.map((destination) => (
                <Item key={destination.key} variant="outline" size="sm">
                    <ItemContent className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                            <ItemTitle className="truncate">{destination.title}</ItemTitle>
                            <DestinationTag label="Pending" type="warning" tooltip={tooltip} />
                        </div>
                        {destination.detail ? (
                            <ItemDescription className="truncate">{destination.detail}</ItemDescription>
                        ) : null}
                    </ItemContent>
                    <ItemActions>
                        <Button
                            variant="destructive-outline"
                            size="icon-sm"
                            onClick={destination.onRemove}
                            aria-label="Remove notification"
                            tooltip="Remove notification"
                        >
                            <IconTrash />
                        </Button>
                    </ItemActions>
                </Item>
            ))}
        </div>
    )
}

export function QuillAlertNotificationDestinationEditor<NotificationType extends string>({
    description,
    destinations,
    notificationType,
    slack,
    url,
    pagerduty,
    add,
}: AlertNotificationDestinationEditorProps<NotificationType>): JSX.Element {
    const typeOptions = leafOptions(notificationType.options)

    const addDestinationButton = (
        <Button variant="primary" onClick={add.onClick} disabledReason={add.disabledReason} className="shrink-0">
            Add
        </Button>
    )

    const addDestinationButtonIsInline =
        notificationType.value === slack.notificationType || Boolean(url) || Boolean(pagerduty)

    const addOnEnter = (event: KeyboardEvent<HTMLInputElement>): void => {
        if (event.key === 'Enter') {
            addDestinationOnEnter(event, add)
        }
    }

    let slackDestinationInput: JSX.Element | null = null
    if (notificationType.value === slack.notificationType) {
        if (slack.integrationsLoading || slack.integrations === undefined) {
            slackDestinationInput = <Skeleton className="h-10" />
        } else if (slack.integrationsFailed) {
            slackDestinationInput = (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>Couldn't load Slack workspaces.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={slack.onRetryIntegrations}>
                            Try again
                        </Button>
                    </ItemActions>
                </Item>
            )
        } else if (slack.integration) {
            slackDestinationInput = (
                <div className="flex flex-col gap-3">
                    {(slack.integrations?.length ?? 0) > 1 ? (
                        <FieldSet className="gap-1">
                            <FieldLegend variant="label">Slack workspace</FieldLegend>
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
                        </FieldSet>
                    ) : null}
                    <FieldSet className="gap-1">
                        <FieldLegend variant="label">Channel</FieldLegend>
                        <div className="flex flex-col items-start gap-2 sm:flex-row">
                            <div className="w-full min-w-0 flex-1">
                                <SlackChannelPicker
                                    value={slack.channelValue ?? undefined}
                                    onChange={slack.onChannelValueChange}
                                    integration={slack.integration}
                                />
                            </div>
                            {addDestinationButton}
                        </div>
                    </FieldSet>
                </div>
            )
        } else {
            slackDestinationInput = (
                <SlackNotConfiguredBanner
                    type="warning"
                    className="max-w-4xl"
                    onConnected={slack.onIntegrationChange}
                />
            )
        }
    }

    const hasDestinations =
        (destinations.showExisting && (destinations.existingLoading || destinations.existing.length > 0)) ||
        destinations.pending.length > 0

    return (
        <div className="flex flex-col gap-4" data-prevent-wizard-submit>
            {description ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {description}
                </Text>
            ) : null}

            {destinations.showExisting ? (
                <ExistingDestinations loading={destinations.existingLoading} destinations={destinations.existing} />
            ) : null}

            <PendingDestinations destinations={destinations.pending} tooltip={destinations.pendingTooltip} />

            {hasDestinations ? <Separator /> : null}

            <div className="flex max-w-xl flex-col gap-3">
                <Select
                    items={typeOptions}
                    value={notificationType.value}
                    onValueChange={(value) => value && notificationType.onChange(value)}
                >
                    <SelectTrigger className="w-full" aria-label="Notification type">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {typeOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>

                {slackDestinationInput}

                {url ? (
                    <Field>
                        <div className="flex flex-col items-start gap-2 sm:flex-row">
                            {/* The URL's path carries its secret. Autocapture records copied text, and session
                                replay records what is typed, so the input is kept out of both. */}
                            <Input
                                className="ph-no-capture ph-replay-block"
                                aria-label="Destination URL"
                                placeholder={url.input.placeholder}
                                value={url.value}
                                onChange={(event) => url.onChange(event.target.value)}
                                onKeyDown={addOnEnter}
                            />
                            {addDestinationButton}
                        </div>
                        {url.input.helpText ? <FieldDescription>{url.input.helpText}</FieldDescription> : null}
                    </Field>
                ) : null}

                {pagerduty ? (
                    <div className="flex flex-col gap-3">
                        <Field>
                            <FieldLabel htmlFor="alert-pagerduty-routing-key">Integration key</FieldLabel>
                            <div className="flex flex-col items-start gap-2 sm:flex-row">
                                {/* Autocapture records copied text, which the password type does not stop. */}
                                <Input
                                    id="alert-pagerduty-routing-key"
                                    type="password"
                                    autoComplete="off"
                                    className="ph-no-capture"
                                    placeholder="32-character Events API v2 integration key"
                                    value={pagerduty.routingKey}
                                    onChange={(event) => pagerduty.onRoutingKeyChange(event.target.value)}
                                    onKeyDown={addOnEnter}
                                    data-attr="alert-pagerduty-routing-key"
                                />
                                {addDestinationButton}
                            </div>
                            <FieldDescription>
                                In PagerDuty, add an "Events API v2" integration to the service you want to page and
                                paste its integration key here. An incident opens when the alert starts firing and
                                resolves when it stops.
                            </FieldDescription>
                        </Field>
                        <div className="flex flex-col gap-3 sm:flex-row">
                            <Field className="min-w-0 flex-1">
                                <FieldLabel htmlFor="alert-pagerduty-severity">Severity</FieldLabel>
                                <Select
                                    items={ALERT_PAGERDUTY_SEVERITY_OPTIONS}
                                    value={pagerduty.severity}
                                    onValueChange={(value) => value && pagerduty.onSeverityChange(value)}
                                >
                                    <SelectTrigger
                                        id="alert-pagerduty-severity"
                                        className="w-full"
                                        data-attr="alert-pagerduty-severity"
                                    >
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {ALERT_PAGERDUTY_SEVERITY_OPTIONS.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </Field>
                            <Field className="min-w-0 flex-1">
                                <FieldLabel htmlFor="alert-pagerduty-region">Service region</FieldLabel>
                                <Select
                                    items={ALERT_PAGERDUTY_REGION_OPTIONS}
                                    value={pagerduty.region}
                                    onValueChange={(value) => value && pagerduty.onRegionChange(value)}
                                >
                                    <SelectTrigger
                                        id="alert-pagerduty-region"
                                        className="w-full"
                                        data-attr="alert-pagerduty-region"
                                    >
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {ALERT_PAGERDUTY_REGION_OPTIONS.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </Field>
                        </div>
                    </div>
                ) : null}

                {!addDestinationButtonIsInline ? addDestinationButton : null}
            </div>
        </div>
    )
}
