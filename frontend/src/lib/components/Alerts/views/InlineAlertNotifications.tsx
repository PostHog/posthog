import { useActions, useValues } from 'kea'

import { IconExternal, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import {
    ALERT_NOTIFICATION_TYPE_SLACK,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
    PendingAlertNotification,
} from 'lib/utils/alertUtils'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import { ALERT_NOTIFICATION_TYPE_OPTIONS, alertNotificationLogic } from '../alertNotificationLogic'

function getHogFunctionDestination(hf: HogFunctionType): { type: string; detail: string | null } {
    const channelValue = hf.inputs?.channel?.value
    if (channelValue) {
        let channelName: string | null = null
        if (typeof channelValue === 'string') {
            const parts = channelValue.split('|')
            channelName = parts[1]?.replace('#', '') ?? null
        }
        if (!channelName) {
            const match = hf.name?.match(/Slack #(.+)$/)
            channelName = match?.[1] ?? null
        }
        return { type: 'Slack', detail: channelName ? `#${channelName}` : null }
    }
    const urlValue = hf.inputs?.url?.value
    if (urlValue && typeof urlValue === 'string') {
        return { type: 'Webhook', detail: urlValue }
    }
    return { type: hf.name, detail: null }
}

interface InlineAlertNotificationsProps {
    alertId?: string
}

export function InlineAlertNotifications({ alertId }: InlineAlertNotificationsProps): JSX.Element {
    const logic = alertNotificationLogic({ alertId })
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

    const handleAdd = (): void => {
        if (selectedType === ALERT_NOTIFICATION_TYPE_SLACK) {
            if (!slackChannelValue || !firstSlackIntegration) {
                return
            }
            const channelName = slackChannelValue.split('|')[1]?.replace('#', '') ?? slackChannelValue

            const notification: PendingAlertNotification = {
                type: ALERT_NOTIFICATION_TYPE_SLACK,
                slackWorkspaceId: firstSlackIntegration.id,
                slackChannelId: slackChannelValue,
                slackChannelName: channelName,
            }
            addPendingNotification(notification)
            setSlackChannelValue(null)
        } else {
            if (!webhookUrl) {
                return
            }
            addPendingNotification({ type: ALERT_NOTIFICATION_TYPE_WEBHOOK, webhookUrl })
            setWebhookUrl('')
        }
    }

    const getNotificationLabel = (notification: PendingAlertNotification): string => {
        if (notification.type === ALERT_NOTIFICATION_TYPE_SLACK) {
            return `Slack: #${notification.slackChannelName ?? 'channel'}`
        }
        return `Webhook: ${notification.webhookUrl}`
    }

    return (
        <div className="space-y-4">
            {alertId && (
                <div>
                    {existingHogFunctionsLoading ? (
                        <LemonSkeleton className="h-8" repeat={2} />
                    ) : existingHogFunctions.length > 0 ? (
                        <div className="space-y-2">
                            {existingHogFunctions.map((hf) => {
                                const { type: destType, detail } = getHogFunctionDestination(hf)
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
                                            <LemonButton
                                                icon={<IconTrash />}
                                                size="xsmall"
                                                status="danger"
                                                onClick={() => deleteExistingHogFunction(hf)}
                                                tooltip="Delete notification"
                                            />
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
                                tooltip="Remove notification"
                            />
                        </div>
                    ))}
                </div>
            )}

            <div className="space-y-3 border rounded p-3">
                <div className="flex gap-2 items-end">
                    <div className="flex-1">
                        <LemonSelect
                            fullWidth
                            options={ALERT_NOTIFICATION_TYPE_OPTIONS}
                            value={selectedType}
                            onChange={(value) => setSelectedType(value)}
                        />
                    </div>
                </div>

                {selectedType === ALERT_NOTIFICATION_TYPE_SLACK && (
                    <>
                        {!firstSlackIntegration ? (
                            <SlackNotConfiguredBanner />
                        ) : (
                            <SlackChannelPicker
                                value={slackChannelValue ?? undefined}
                                onChange={(value) => setSlackChannelValue(value)}
                                integration={firstSlackIntegration}
                            />
                        )}
                    </>
                )}

                {selectedType === ALERT_NOTIFICATION_TYPE_WEBHOOK && (
                    <LemonInput
                        placeholder="https://example.com/webhook"
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
                        selectedType === ALERT_NOTIFICATION_TYPE_SLACK
                            ? !firstSlackIntegration
                                ? 'Connect Slack first'
                                : !slackChannelValue
                                  ? 'Select a Slack channel'
                                  : undefined
                            : !webhookUrl
                              ? 'Enter a webhook URL'
                              : undefined
                    }
                >
                    Add notification
                </LemonButton>
            </div>
        </div>
    )
}
