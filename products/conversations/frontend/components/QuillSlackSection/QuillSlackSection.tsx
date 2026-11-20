import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Badge,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Separator,
} from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { confirmRemoveSlackBot, slackChannelOptions } from '../../scenes/settings/slackSettingsHelpers'
import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'
import { QuillSettingsSwitchRow } from '../QuillSettingsSwitchRow/QuillSettingsSwitchRow'
import { QuillSlackChannelMultiSelect } from '../QuillSlackChannelMultiSelect/QuillSlackChannelMultiSelect'

export function QuillSlackSection(): JSX.Element {
    const {
        slackConnected,
        slackChannelIds,
        slackChannels,
        slackChannelsLoading,
        slackTicketEmoji,
        slackTicketEmojiValue,
        slackBotIconUrl,
        slackBotIconUrlValue,
        slackBotDisplayName,
        slackBotDisplayNameValue,
        slackNotifyOnJoin,
        slackNotifyOnLeave,
        slackAlertChannelId,
        slackNudgeEnabled,
        slackNeedsReconnect,
        currentTeamLoading,
    } = useValues(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const memberAlertsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_SLACK_NOTIFY_ON_MEMBERS]
    const {
        connectSlack,
        setSlackChannels,
        loadSlackChannelsWithToken,
        setSlackTicketEmojiValue,
        saveSlackTicketEmoji,
        setSlackBotIconUrlValue,
        setSlackBotDisplayNameValue,
        saveSlackBotSettings,
        setSlackNotifyOnJoin,
        setSlackNotifyOnLeave,
        setSlackAlertChannel,
        setSlackNudgeEnabled,
        disconnectSlack,
    } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const channelsId = useId()
    const alertChannelId = useId()
    const emojiId = useId()
    const botNameId = useId()

    const channelOptions = slackChannelOptions(slackChannels)
    const channelLabels = new Map(channelOptions.map((option) => [option.key, option.label]))
    const refreshDisabledReason = slackChannelsLoading ? 'Loading channels...' : undefined

    function connect(): void {
        connectSlack(window.location.pathname)
    }

    return (
        <QuillSettingsSubsection
            title="SupportHog Slack bot"
            description={
                <>
                    Add the SupportHog bot to your Slack workspace to create and manage support tickets directly from
                    Slack messages.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/support/slack" target="_blank" />}
                    >
                        Docs
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <Field>
                    <FieldLabel>Connection</FieldLabel>
                    <FieldDescription>
                        Install the SupportHog bot in your Slack workspace to enable support ticket creation from
                        channels, mentions, and emoji reactions. This is separate from the main PostHog Slack
                        integration.
                    </FieldDescription>
                    {!slackConnected && (
                        <div>
                            <Button variant="primary" disabledReason={adminRestrictionReason} onClick={connect}>
                                Add SupportHog to Slack
                            </Button>
                        </div>
                    )}
                    {slackNeedsReconnect && (
                        <Item tone="warning" size="sm">
                            <ItemContent>
                                <ItemDescription>
                                    Files sent in Slack won't appear on tickets, and images you send from PostHog arrive
                                    as links instead of attachments. Reconnect SupportHog to give it access to files.
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Button variant="outline" disabledReason={adminRestrictionReason} onClick={connect}>
                                    Reconnect
                                </Button>
                            </ItemActions>
                        </Item>
                    )}
                </Field>

                {slackConnected && (
                    <>
                        <Separator />
                        <Field>
                            <FieldLabel htmlFor={channelsId}>Support channels</FieldLabel>
                            <FieldDescription>
                                Messages posted in any of these channels will automatically create support tickets.
                                Thread replies become ticket messages. Make sure the SupportHog bot is invited to every
                                selected channel.
                            </FieldDescription>
                            <div className="flex flex-wrap items-center gap-2">
                                <div className="min-w-60 flex-1">
                                    <QuillSlackChannelMultiSelect
                                        id={channelsId}
                                        options={channelOptions}
                                        value={slackChannelIds}
                                        placeholder="Select channels"
                                        onChange={(newValue: string[]) => setSlackChannels(newValue)}
                                    />
                                </div>
                                <Button
                                    variant="outline"
                                    onClick={loadSlackChannelsWithToken}
                                    loading={slackChannelsLoading}
                                    disabledReason={refreshDisabledReason}
                                >
                                    Refresh
                                </Button>
                            </div>
                        </Field>

                        <Separator />
                        <div className="flex flex-col gap-2">
                            <Field>
                                <FieldLabel>Ticket nudges</FieldLabel>
                                <FieldDescription>
                                    When enabled, SupportHog replies in-thread asking whether the customer wants to open
                                    a ticket. This means customers don't have to remember the emoji reaction or
                                    @mention. 'Support channels' will still have tickets created for every thread, and
                                    no nudge is sent.
                                </FieldDescription>
                            </Field>
                            <QuillSettingsSwitchRow
                                label="Nudge users to open tickets"
                                checked={slackNudgeEnabled}
                                onCheckedChange={setSlackNudgeEnabled}
                                loading={currentTeamLoading}
                            />
                        </div>

                        {memberAlertsEnabled && (
                            <>
                                <Separator />
                                <div className="flex flex-col gap-2">
                                    <Field>
                                        <FieldLabel>Channel membership alerts</FieldLabel>
                                        <FieldDescription>
                                            Notify a channel when someone joins or leaves any channel the SupportHog bot
                                            is in.
                                        </FieldDescription>
                                    </Field>
                                    <QuillSettingsSwitchRow
                                        label="Alert when someone joins a channel"
                                        checked={slackNotifyOnJoin}
                                        onCheckedChange={setSlackNotifyOnJoin}
                                        loading={currentTeamLoading}
                                    />
                                    <QuillSettingsSwitchRow
                                        label="Alert when someone leaves a channel"
                                        checked={slackNotifyOnLeave}
                                        onCheckedChange={setSlackNotifyOnLeave}
                                        loading={currentTeamLoading}
                                    />
                                    <div className="flex flex-wrap items-center gap-2">
                                        <Combobox
                                            items={channelOptions.map((option) => option.key)}
                                            value={slackAlertChannelId}
                                            onValueChange={(next: string | null) => setSlackAlertChannel(next ?? null)}
                                            itemToStringLabel={(key: string) => channelLabels.get(key) ?? key}
                                        >
                                            <ComboboxInput
                                                id={alertChannelId}
                                                aria-label="Alerts channel"
                                                className="min-w-60 flex-1"
                                                placeholder="Select alerts channel"
                                                disabled={currentTeamLoading}
                                                disabledReason={
                                                    !slackNotifyOnJoin && !slackNotifyOnLeave
                                                        ? 'Turn on a join or leave alert to pick a channel'
                                                        : undefined
                                                }
                                            />
                                            <ComboboxContent>
                                                <ComboboxEmpty>No matching channels</ComboboxEmpty>
                                                <ComboboxList>
                                                    {(key: string) => (
                                                        <ComboboxItem key={key} value={key}>
                                                            {channelLabels.get(key) ?? key}
                                                        </ComboboxItem>
                                                    )}
                                                </ComboboxList>
                                            </ComboboxContent>
                                        </Combobox>
                                        <Button
                                            variant="outline"
                                            onClick={loadSlackChannelsWithToken}
                                            loading={slackChannelsLoading}
                                            disabledReason={refreshDisabledReason}
                                        >
                                            Refresh
                                        </Button>
                                    </div>
                                </div>
                            </>
                        )}

                        <Separator />
                        <Field>
                            <FieldLabel htmlFor={emojiId}>Ticket emoji trigger</FieldLabel>
                            <FieldDescription>
                                React with this emoji on any message to create a support ticket from it.
                            </FieldDescription>
                            <div className="flex flex-wrap items-center gap-2">
                                <Input
                                    id={emojiId}
                                    className="w-50"
                                    value={slackTicketEmojiValue ?? slackTicketEmoji}
                                    onChange={(event) => setSlackTicketEmojiValue(event.target.value)}
                                    placeholder="ticket"
                                />
                                <Button
                                    variant="primary"
                                    onClick={saveSlackTicketEmoji}
                                    disabledReason={!slackTicketEmojiValue ? 'Enter an emoji name' : undefined}
                                >
                                    Save
                                </Button>
                            </div>
                        </Field>

                        <Separator />
                        <Field>
                            <FieldLabel htmlFor={botNameId}>Bot appearance</FieldLabel>
                            <FieldDescription>
                                Override the bot's display name and icon when posting messages. Leave blank to use
                                defaults. Requires the bot to be re-authorized if it was connected before this feature
                                was available.
                            </FieldDescription>
                            <Input
                                id={botNameId}
                                value={slackBotDisplayNameValue ?? slackBotDisplayName ?? ''}
                                onChange={(event) => setSlackBotDisplayNameValue(event.target.value)}
                                placeholder="Display name (e.g. SupportHog)"
                            />
                            <Input
                                aria-label="Icon URL"
                                value={slackBotIconUrlValue ?? slackBotIconUrl ?? ''}
                                onChange={(event) => setSlackBotIconUrlValue(event.target.value)}
                                placeholder="Icon URL (e.g. https://example.com/icon.png)"
                            />
                            <div>
                                <Button
                                    variant="primary"
                                    onClick={saveSlackBotSettings}
                                    disabledReason={
                                        slackBotDisplayNameValue === null && slackBotIconUrlValue === null
                                            ? 'No changes to save'
                                            : undefined
                                    }
                                >
                                    Save
                                </Button>
                            </div>
                        </Field>

                        <Separator />
                        <Field orientation="horizontal">
                            <FieldContent>
                                <FieldLabel>Bot mention</FieldLabel>
                                <FieldDescription>
                                    Users can @mention the bot in any channel to create a support ticket.
                                </FieldDescription>
                            </FieldContent>
                            <Badge variant="success">Active</Badge>
                        </Field>

                        <Separator />
                        <div className="flex justify-end">
                            <Button
                                variant="destructive-outline"
                                disabledReason={adminRestrictionReason}
                                onClick={() => confirmRemoveSlackBot(disconnectSlack)}
                            >
                                Remove SupportHog bot
                            </Button>
                        </div>
                    </>
                )}
            </div>
        </QuillSettingsSubsection>
    )
}
