import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExternal, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { urls } from 'scenes/urls'

import { HogFunctionType, SlackChannelType } from '~/types'

import { SUBSCRIPTION_NOTIFICATION_TYPE_OPTIONS, subscriptionNotificationLogic } from '../subscriptionNotificationLogic'
import {
    PendingSubscriptionNotification,
    SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD,
    SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
    SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK,
    isPinnedToSubscription,
} from '../subscriptionNotificationUtils'

function resolveSlackChannelName(channelValue: string, slackChannels: SlackChannelType[]): string | null {
    const channelId = channelValue.split('|')[0]
    return slackChannels.find((c) => c.id === channelId)?.name ?? null
}

function getHogFunctionDestination(
    hf: HogFunctionType,
    slackChannels: SlackChannelType[]
): { type: string; detail: string | null } {
    const channelValue = hf.inputs?.channel?.value
    if (channelValue && typeof channelValue === 'string') {
        const channelName = resolveSlackChannelName(channelValue, slackChannels)
        return { type: 'Slack', detail: channelName ? `#${channelName}` : null }
    }
    if (channelValue) {
        return { type: 'Slack', detail: null }
    }
    if (hf.template_id === 'template-discord') {
        const webhookUrl = hf.inputs?.webhookUrl?.value
        return { type: 'Discord', detail: typeof webhookUrl === 'string' ? webhookUrl : null }
    }
    const urlValue = hf.inputs?.url?.value
    if (urlValue && typeof urlValue === 'string') {
        return { type: 'Webhook', detail: urlValue }
    }
    return { type: hf.name, detail: null }
}

interface InlineSubscriptionNotificationsProps {
    subscriptionId?: number
}

export function InlineSubscriptionNotifications({ subscriptionId }: InlineSubscriptionNotificationsProps): JSX.Element {
    const logic = subscriptionNotificationLogic({ subscriptionId })
    const {
        existingHogFunctions,
        existingHogFunctionsLoading,
        pendingNotifications,
        firstSlackIntegration,
        selectedType,
        slackChannelValue,
        webhookUrl,
    } = useValues(logic)
    const {
        addPendingNotification,
        removePendingNotification,
        deleteExistingHogFunction,
        setSelectedType,
        setSlackChannelValue,
        setWebhookUrl,
    } = useActions(logic)

    // Non-admins can see what's wired but can't add/configure destinations (mirrors the destinations library).
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const slackLogic = slackIntegrationLogic({ id: firstSlackIntegration?.id ?? 0 })
    const { slackChannels } = useValues(slackLogic)
    const { loadAllSlackChannels } = useActions(slackLogic)

    useEffect(() => {
        if (firstSlackIntegration) {
            loadAllSlackChannels()
        }
    }, [firstSlackIntegration?.id, loadAllSlackChannels, firstSlackIntegration])

    const handleAdd = (): void => {
        if (selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_SLACK) {
            if (!slackChannelValue || !firstSlackIntegration) {
                return
            }
            const parts = slackChannelValue.split('|')
            const channelId = parts[0]
            const channelName = parts[1]?.replace('#', '') ?? channelId
            addPendingNotification({
                type: SUBSCRIPTION_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: firstSlackIntegration.id,
                slackChannelId: channelId,
                slackChannelName: channelName,
            })
            setSlackChannelValue(null)
            return
        }

        if (!webhookUrl) {
            return
        }
        addPendingNotification(
            selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD
                ? { type: SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD, webhookUrl }
                : { type: SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK, webhookUrl }
        )
        setWebhookUrl('')
    }

    const getNotificationLabel = (notification: PendingSubscriptionNotification): string => {
        if (notification.type === SUBSCRIPTION_NOTIFICATION_TYPE_SLACK) {
            return `Slack: #${notification.slackChannelName ?? 'channel'}`
        }
        if (notification.type === SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD) {
            return `Discord: ${notification.webhookUrl}`
        }
        return `Webhook: ${notification.webhookUrl}`
    }

    return (
        <div className="space-y-4">
            {subscriptionId != null && (
                <div>
                    {existingHogFunctionsLoading ? (
                        <LemonSkeleton className="h-8" repeat={2} />
                    ) : existingHogFunctions.length > 0 ? (
                        <div className="space-y-2">
                            {existingHogFunctions.map((hf) => {
                                const { type: destType, detail } = getHogFunctionDestination(hf, slackChannels)
                                // Team-wide destinations fire for every report and are managed in the library, so
                                // they're read-only here; only this-subscription destinations are deletable.
                                const thisSub = isPinnedToSubscription(hf, subscriptionId)
                                return (
                                    <div
                                        key={hf.id}
                                        className="flex items-center justify-between border rounded p-2 gap-2"
                                    >
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-medium">{destType}</span>
                                                <LemonTag type={hf.enabled ? 'success' : 'default'} size="small">
                                                    {hf.enabled ? 'Active' : 'Paused'}
                                                </LemonTag>
                                                {!thisSub && (
                                                    <LemonTag type="muted" size="small">
                                                        All reports
                                                    </LemonTag>
                                                )}
                                            </div>
                                            {detail && (
                                                <span className="text-xs text-muted-alt truncate block">{detail}</span>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-1 shrink-0">
                                            <LemonButton
                                                icon={<IconExternal />}
                                                size="xsmall"
                                                to={urls.hogFunction(hf.id)}
                                                targetBlank
                                                hideExternalLinkIcon
                                                tooltip="Open destination"
                                            />
                                            {thisSub && !restrictedReason && (
                                                <LemonButton
                                                    icon={<IconTrash />}
                                                    size="xsmall"
                                                    status="danger"
                                                    onClick={() => deleteExistingHogFunction(hf)}
                                                    tooltip="Delete automation"
                                                />
                                            )}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    ) : null}
                </div>
            )}

            {pendingNotifications.length > 0 && (
                <div className="space-y-2">
                    {pendingNotifications.map((notification, index) => (
                        <div key={index} className="flex items-center justify-between border rounded p-2 gap-2">
                            <span className="text-sm min-w-0 truncate">
                                {getNotificationLabel(notification)}{' '}
                                <span className="text-muted-alt">(pending - click Save to apply)</span>
                            </span>
                            <LemonButton
                                icon={<IconTrash />}
                                size="xsmall"
                                status="danger"
                                onClick={() => removePendingNotification(index)}
                                tooltip="Remove automation"
                            />
                        </div>
                    ))}
                </div>
            )}

            {restrictedReason ? (
                existingHogFunctions.length === 0 &&
                pendingNotifications.length === 0 && (
                    <span className="text-xs text-muted-alt">No automations connected to this subscription.</span>
                )
            ) : (
                <div className="space-y-3 border rounded p-3">
                    <div className="flex gap-2 items-end">
                        <div className="flex-1">
                            <LemonSelect
                                fullWidth
                                options={SUBSCRIPTION_NOTIFICATION_TYPE_OPTIONS}
                                value={selectedType}
                                onChange={(value) => setSelectedType(value)}
                            />
                        </div>
                    </div>

                    {selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_SLACK &&
                        (!firstSlackIntegration ? (
                            <SlackNotConfiguredBanner />
                        ) : (
                            <SlackChannelPicker
                                value={slackChannelValue ?? undefined}
                                onChange={(value) => setSlackChannelValue(value)}
                                integration={firstSlackIntegration}
                            />
                        ))}

                    {(selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_WEBHOOK ||
                        selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD) && (
                        <LemonInput
                            placeholder={
                                selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD
                                    ? 'https://discord.com/api/webhooks/...'
                                    : 'https://example.com/webhook'
                            }
                            value={webhookUrl}
                            onChange={setWebhookUrl}
                            fullWidth
                        />
                    )}

                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={handleAdd}
                        disabledReason={
                            selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_SLACK
                                ? !firstSlackIntegration
                                    ? 'Connect Slack first'
                                    : !slackChannelValue
                                      ? 'Select a Slack channel'
                                      : undefined
                                : !webhookUrl
                                  ? selectedType === SUBSCRIPTION_NOTIFICATION_TYPE_DISCORD
                                      ? 'Enter a Discord webhook URL'
                                      : 'Enter a webhook URL'
                                  : undefined
                        }
                    >
                        Add automation
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
