import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { urls } from 'scenes/urls'

import type { IntegrationType } from '~/types'

import { eventStreamLogic } from './eventStreamLogic'

function ConnectSlackPrompt(): JSX.Element {
    return (
        <LemonBanner type="info">
            <Link to={urls.settings('environment-integrations', 'integration-slack')}>Connect a Slack workspace</Link>{' '}
            to deliver the event stream to a channel.
        </LemonBanner>
    )
}

export function CustomerAnalyticsEventStream(): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { eventStream, eventStreamLoading } = useValues(eventStreamLogic)
    const { saveEventStream } = useActions(eventStreamLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)

    if ((integrationsLoading && slackIntegrations === undefined) || (eventStreamLoading && eventStream === null)) {
        return <LemonSkeleton className="h-20 w-full" />
    }

    const integrations: IntegrationType[] = slackIntegrations ?? []
    const selectedIntegration =
        integrations.find((integration) => integration.id === eventStream?.slack_integration) ??
        (integrations.length === 1 ? integrations[0] : null)
    const channelValue = eventStream?.slack_channel_id
        ? `${eventStream.slack_channel_id}|${eventStream.slack_channel_name || ''}`
        : undefined
    const memberCount = eventStream?.account_ids?.length ?? 0

    const onChannelChange = (value: string | null): void => {
        if (!selectedIntegration) {
            return
        }
        const [channelId, ...nameParts] = (value ?? '').split('|')
        saveEventStream({
            slack_integration: selectedIntegration.id,
            slack_channel_id: channelId,
            slack_channel_name: nameParts.join('|'),
        })
    }

    return (
        <div className="flex flex-col gap-4">
            <p className="mb-0">
                Stream the events of selected customers to a Slack channel in real time. Choose which events to watch
                here, then add customers to the stream from their account profiles.
            </p>

            <div className="flex flex-col gap-2">
                <h4 className="secondary uppercase text-secondary mb-0">Events to stream</h4>
                <EventSelect
                    onChange={(names) => saveEventStream({ event_names: names })}
                    selectedEvents={eventStream?.event_names ?? []}
                    addElement={
                        <LemonButton size="small" type="secondary" icon={<IconPlus />} disabled={eventStreamLoading}>
                            Add event
                        </LemonButton>
                    }
                />
            </div>

            <div className="flex flex-col gap-2">
                <h4 className="secondary uppercase text-secondary mb-0">Slack delivery</h4>
                {integrations.length === 0 ? (
                    <ConnectSlackPrompt />
                ) : (
                    <div className="flex flex-col gap-2 max-w-160">
                        {integrations.length > 1 && (
                            <LemonSelect
                                value={selectedIntegration?.id ?? null}
                                placeholder="Select a Slack workspace"
                                options={integrations.map((integration) => ({
                                    value: integration.id,
                                    label: integration.display_name,
                                }))}
                                onChange={(integrationId) =>
                                    // Switching workspaces clears the channel — it won't exist in the new workspace.
                                    saveEventStream({
                                        slack_integration: integrationId,
                                        slack_channel_id: '',
                                        slack_channel_name: '',
                                    })
                                }
                                disabled={eventStreamLoading}
                            />
                        )}
                        {selectedIntegration && (
                            <SlackChannelPicker
                                integration={selectedIntegration}
                                value={channelValue}
                                onChange={onChannelChange}
                                disabled={eventStreamLoading}
                            />
                        )}
                    </div>
                )}
            </div>

            <div className="flex flex-col gap-2">
                <h4 className="secondary uppercase text-secondary mb-0">Customers in the stream</h4>
                <p className="mb-0 text-secondary">
                    {memberCount === 0
                        ? 'No customers yet — open an account in '
                        : `${memberCount} ${memberCount === 1 ? 'customer' : 'customers'} in the stream. Manage them from `}
                    <Link to={urls.customerAnalyticsAccounts()}>the accounts list</Link> and use the "Include in event
                    stream" toggle on the account's profile.
                </p>
            </div>

            <LemonSwitch
                checked={eventStream?.enabled ?? false}
                onChange={(enabled) => saveEventStream({ enabled })}
                disabledReason={eventStreamLoading ? 'Saving…' : undefined}
                label="Enable event stream"
                bordered
            />
            {eventStream?.enabled &&
                (!eventStream.event_names?.length || !eventStream.slack_channel_id || memberCount === 0) && (
                    <LemonBanner type="warning">
                        The stream is enabled but won't deliver anything yet — it still needs
                        {!eventStream.event_names?.length ? ' at least one event,' : ''}
                        {!eventStream.slack_channel_id ? ' a Slack channel,' : ''}
                        {memberCount === 0 ? ' at least one customer,' : ''} before events start flowing.
                    </LemonBanner>
                )}
        </div>
    )
}
