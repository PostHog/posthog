import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, Heading, Item, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { QuillOptionSelect } from 'scenes/settings/environment/QuillOptionSelect'
import { urls } from 'scenes/urls'

import { eventStreamLogic } from './eventStreamLogic'

function SectionHeading({ children }: { children: string }): JSX.Element {
    return (
        <Heading size="sm" render={<h4 className="m-0" />}>
            {children}
        </Heading>
    )
}

export function QuillCustomerAnalyticsEventStream(): JSX.Element {
    const {
        eventStream,
        eventStreamLoading,
        draft,
        hasChanges,
        testMessageLoading,
        integrations,
        selectedIntegration,
        slackChannelValue,
        memberCount,
        testMessageDisabledReason,
    } = useValues(eventStreamLogic)
    const { setDraft, resetDraft, saveEventStream, sendTestMessage, setSlackIntegration, setSlackChannel } =
        useActions(eventStreamLogic)

    const changesDisabledReason = hasChanges ? undefined : 'No changes'

    return (
        <div className="flex flex-col gap-4">
            <Text size="xs" render={<p className="m-0" />}>
                Stream the events of selected customers to a Slack channel of your choice in real time. This is your
                personal stream — each team member configures their own. Choose which events to watch here, then add
                customers to the stream from their account profiles.
            </Text>

            <div className="flex flex-col gap-2">
                <SectionHeading>Events to stream</SectionHeading>
                <EventSelect
                    onChange={(names) => setDraft({ event_names: names })}
                    selectedEvents={draft.event_names}
                    addElement={
                        <Button variant="outline">
                            <IconPlus />
                            Add event
                        </Button>
                    }
                />
            </div>

            <div className="flex flex-col gap-2">
                <SectionHeading>Slack delivery</SectionHeading>
                {integrations.length === 0 ? (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to={urls.settings('environment-integrations', 'integration-slack')}
                                        />
                                    }
                                >
                                    Connect a Slack workspace
                                </Button>{' '}
                                to deliver the event stream to a channel.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ) : (
                    <div className="flex max-w-160 flex-col gap-2">
                        {integrations.length > 1 && (
                            <QuillOptionSelect
                                value={selectedIntegration?.id ?? null}
                                placeholder="Select a Slack workspace"
                                ariaLabel="Slack workspace"
                                options={integrations.map((integration) => ({
                                    value: integration.id,
                                    label: integration.display_name,
                                }))}
                                onChange={setSlackIntegration}
                            />
                        )}
                        {selectedIntegration && (
                            <SlackChannelPicker
                                integration={selectedIntegration}
                                value={slackChannelValue}
                                onChange={setSlackChannel}
                            />
                        )}
                        <div>
                            <Button
                                variant="outline"
                                onClick={sendTestMessage}
                                loading={testMessageLoading}
                                disabledReason={testMessageDisabledReason}
                                data-attr="event-stream-send-test-message"
                            >
                                Send test message
                            </Button>
                        </div>
                    </div>
                )}
            </div>

            <div className="flex flex-col gap-2">
                <SectionHeading>Customers in your stream</SectionHeading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {memberCount === 0
                        ? 'No customers yet — open an account in '
                        : `${memberCount} ${memberCount === 1 ? 'customer' : 'customers'} in your stream. Manage them from `}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.customerAnalyticsAccounts()} />}
                    >
                        the accounts list
                    </Button>{' '}
                    and use the "Include in event stream" toggle on the account's profile.
                </Text>
            </div>

            <QuillSettingSwitch
                label="Enable event stream"
                checked={draft.enabled}
                onCheckedChange={(enabled) => setDraft({ enabled })}
            />
            {eventStream?.enabled &&
                (!eventStream.event_names?.length || !eventStream.slack_channel_id || memberCount === 0) && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                The stream is enabled but won't deliver anything yet — it still needs
                                {!eventStream.event_names?.length ? ' at least one event,' : ''}
                                {!eventStream.slack_channel_id ? ' a Slack channel,' : ''}
                                {memberCount === 0 ? ' at least one customer,' : ''} before events start flowing.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                )}

            <div className="flex flex-row flex-wrap gap-2 pt-2">
                <Button variant="outline" onClick={resetDraft} disabledReason={changesDisabledReason}>
                    Clear changes
                </Button>
                <Button
                    data-attr="save-customer-analytics-event-stream"
                    variant="primary"
                    onClick={saveEventStream}
                    loading={eventStreamLoading}
                    disabledReason={changesDisabledReason}
                >
                    Save
                </Button>
            </div>
        </div>
    )
}
