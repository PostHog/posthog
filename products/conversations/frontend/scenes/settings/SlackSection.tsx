import { useActions, useValues } from 'kea'
import type { ChangeEvent } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Badge,
    Button,
    Card,
    CardContent,
    Checkbox,
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    Input,
    Label,
    Separator,
    useComboboxAnchor,
} from 'lib/ui/quill'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function SlackSection(): JSX.Element {
    return (
        <SceneSection
            title="SupportHog Slack bot"
            description={
                <>
                    Add the SupportHog bot to your Slack workspace to create and manage support tickets directly from
                    Slack messages.{' '}
                    <Link to="https://posthog.com/docs/support/slack" target="_blank">
                        Docs
                    </Link>
                </>
            }
        >
            <Card size="sm" className="max-w-[800px]">
                <CardContent>
                    <SlackChannelSection />
                </CardContent>
            </Card>
        </SceneSection>
    )
}

function SlackChannelSection(): JSX.Element {
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

    const channelOptions = slackChannels.map((c) => ({ id: c.id, label: `#${c.name ?? c.id}` }))
    const refreshDisabledReason = slackChannelsLoading ? 'Loading channels...' : undefined
    const emojiDisabledReason = !slackTicketEmojiValue ? 'Enter an emoji name' : undefined
    const botSettingsDisabledReason =
        slackBotDisplayNameValue === null && slackBotIconUrlValue === null ? 'No changes to save' : undefined
    const alertsDisabled = currentTeamLoading || (!slackNotifyOnJoin && !slackNotifyOnLeave)

    return (
        <div className="flex flex-col gap-y-2">
            <div>
                <label className="font-medium">Connection</label>
                <p className="text-xs text-muted-alt">
                    Install the SupportHog bot in your Slack workspace to enable support ticket creation from channels,
                    mentions, and emoji reactions. This is separate from the main PostHog Slack integration.
                </p>
                {!slackConnected && (
                    <Button
                        className="mt-2"
                        variant="primary"
                        size="sm"
                        disabled={!!adminRestrictionReason}
                        title={adminRestrictionReason ?? undefined}
                        onClick={() => connectSlack(window.location.pathname)}
                    >
                        Add SupportHog to Slack
                    </Button>
                )}
                {slackNeedsReconnect && (
                    <div className="rounded border border-warning bg-warning-highlight p-2 text-sm mt-2 flex flex-col gap-2">
                        <span>
                            Files sent in Slack won't appear on tickets, and images you send from PostHog arrive as
                            links instead of attachments. Reconnect SupportHog to give it access to files.
                        </span>
                        <div>
                            <Button
                                variant="primary"
                                size="sm"
                                disabled={!!adminRestrictionReason}
                                title={adminRestrictionReason ?? undefined}
                                onClick={() => connectSlack(window.location.pathname)}
                            >
                                Reconnect
                            </Button>
                        </div>
                    </div>
                )}
            </div>
            {slackConnected && (
                <>
                    <Separator />
                    <div className="gap-4">
                        <div>
                            <label className="font-medium">Support channels</label>
                            <p className="text-xs text-muted-alt">
                                Messages posted in any of these channels will automatically create support tickets.
                                Thread replies become ticket messages. Make sure the SupportHog bot is invited to every
                                selected channel.
                            </p>
                        </div>
                        <div className="flex gap-2 items-center">
                            <div className="min-w-0 flex-1">
                                <LabeledIdsCombobox
                                    options={channelOptions}
                                    value={slackChannelIds}
                                    onChange={setSlackChannels}
                                    placeholder="Select channels"
                                    disabled={slackChannelsLoading}
                                />
                            </div>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={loadSlackChannelsWithToken}
                                disabled={!!refreshDisabledReason}
                                title={refreshDisabledReason}
                            >
                                Refresh
                            </Button>
                        </div>
                    </div>
                    <Separator />
                    <div className="flex flex-col gap-2">
                        <div>
                            <label className="font-medium">Ticket nudges</label>
                            <p className="text-xs text-muted-alt">
                                When enabled, SupportHog replies in-thread asking whether the customer wants to open a
                                ticket. This means customers don't have to remember the emoji reaction or @mention.
                                'Support channels' will still have tickets created for every thread, and no nudge is
                                sent.
                            </p>
                        </div>
                        <div className="flex items-center gap-2">
                            <Checkbox
                                id="slack-nudge"
                                checked={slackNudgeEnabled}
                                onCheckedChange={(checked) => setSlackNudgeEnabled(!!checked)}
                                disabled={currentTeamLoading}
                            />
                            <Label htmlFor="slack-nudge" className="font-normal">
                                Nudge users to open tickets
                            </Label>
                        </div>
                    </div>
                    {memberAlertsEnabled && (
                        <>
                            <Separator />
                            <div className="flex flex-col gap-2">
                                <div>
                                    <label className="font-medium">Channel membership alerts</label>
                                    <p className="text-xs text-muted-alt">
                                        Notify a channel when someone joins or leaves any channel the SupportHog bot is
                                        in.
                                    </p>
                                </div>
                                <div className="flex items-center gap-2">
                                    <Checkbox
                                        id="slack-notify-join"
                                        checked={slackNotifyOnJoin}
                                        onCheckedChange={(checked) => setSlackNotifyOnJoin(!!checked)}
                                        disabled={currentTeamLoading}
                                    />
                                    <Label htmlFor="slack-notify-join" className="font-normal">
                                        Alert when someone joins a channel
                                    </Label>
                                </div>
                                <div className="flex items-center gap-2">
                                    <Checkbox
                                        id="slack-notify-leave"
                                        checked={slackNotifyOnLeave}
                                        onCheckedChange={(checked) => setSlackNotifyOnLeave(!!checked)}
                                        disabled={currentTeamLoading}
                                    />
                                    <Label htmlFor="slack-notify-leave" className="font-normal">
                                        Alert when someone leaves a channel
                                    </Label>
                                </div>
                                <div className="flex gap-2 items-center">
                                    <div className="min-w-0 flex-1">
                                        <LabeledIdCombobox
                                            options={channelOptions}
                                            value={slackAlertChannelId}
                                            onChange={setSlackAlertChannel}
                                            placeholder="Select alerts channel"
                                            disabled={alertsDisabled || slackChannelsLoading}
                                        />
                                    </div>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={loadSlackChannelsWithToken}
                                        disabled={!!refreshDisabledReason}
                                        title={refreshDisabledReason}
                                    >
                                        Refresh
                                    </Button>
                                </div>
                            </div>
                        </>
                    )}
                    <Separator />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Ticket emoji trigger</label>
                            <p className="text-xs text-muted-alt">
                                React with this emoji on any message to create a support ticket from it.
                            </p>
                        </div>
                        <div className="flex gap-2 items-center">
                            <Input
                                value={slackTicketEmojiValue ?? slackTicketEmoji}
                                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                    setSlackTicketEmojiValue(e.target.value)
                                }
                                placeholder="ticket"
                                className="max-w-[200px]"
                            />
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={saveSlackTicketEmoji}
                                disabled={!!emojiDisabledReason}
                                title={emojiDisabledReason}
                            >
                                Save
                            </Button>
                        </div>
                    </div>
                    <Separator />
                    <div className="flex flex-col gap-2">
                        <div>
                            <label className="font-medium">Bot appearance</label>
                            <p className="text-xs text-muted-alt">
                                Override the bot's display name and icon when posting messages. Leave blank to use
                                defaults. Requires the bot to be re-authorized if it was connected before this feature
                                was available.
                            </p>
                        </div>
                        <Input
                            value={slackBotDisplayNameValue ?? slackBotDisplayName ?? ''}
                            onChange={(e: ChangeEvent<HTMLInputElement>) => setSlackBotDisplayNameValue(e.target.value)}
                            placeholder="Display name (e.g. SupportHog)"
                            className="flex-1"
                        />
                        <Input
                            value={slackBotIconUrlValue ?? slackBotIconUrl ?? ''}
                            onChange={(e: ChangeEvent<HTMLInputElement>) => setSlackBotIconUrlValue(e.target.value)}
                            placeholder="Icon URL (e.g. https://example.com/icon.png)"
                            className="flex-1"
                        />
                        <div>
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={saveSlackBotSettings}
                                disabled={!!botSettingsDisabledReason}
                                title={botSettingsDisabledReason}
                            >
                                Save
                            </Button>
                        </div>
                    </div>
                    <Separator />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Bot mention</label>
                            <p className="text-xs text-muted-alt">
                                Users can @mention the bot in any channel to create a support ticket.
                            </p>
                        </div>
                        <Badge variant="success">Active</Badge>
                    </div>
                    <Separator />
                    <div className="flex justify-end">
                        <AlertDialog>
                            <AlertDialogTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={!!adminRestrictionReason}
                                        title={adminRestrictionReason ?? undefined}
                                    />
                                }
                            >
                                Remove SupportHog bot
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                                <AlertDialogHeader>
                                    <AlertDialogTitle>Remove SupportHog bot?</AlertDialogTitle>
                                    <AlertDialogDescription>
                                        This will stop creating tickets from Slack messages. Existing tickets will not
                                        be affected.
                                    </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                                    <AlertDialogClose
                                        render={<Button variant="destructive" onClick={disconnectSlack} />}
                                    >
                                        Remove
                                    </AlertDialogClose>
                                </AlertDialogFooter>
                            </AlertDialogContent>
                        </AlertDialog>
                    </div>
                </>
            )}
        </div>
    )
}

function LabeledIdsCombobox({
    options,
    value,
    onChange,
    placeholder,
    disabled,
}: {
    options: { id: string; label: string }[]
    value: string[]
    onChange: (next: string[]) => void
    placeholder: string
    disabled?: boolean
}): JSX.Element {
    const labels = Object.fromEntries(options.map((option) => [option.id, option.label]))
    const items = options.map((option) => option.id)
    return (
        <Combobox multiple items={items} value={value} onValueChange={onChange}>
            <LabeledIdsComboboxBody labels={labels} placeholder={placeholder} disabled={disabled} />
        </Combobox>
    )
}

function LabeledIdsComboboxBody({
    labels,
    placeholder,
    disabled,
}: {
    labels: Record<string, string>
    placeholder: string
    disabled?: boolean
}): JSX.Element {
    const anchor = useComboboxAnchor()
    return (
        <>
            <ComboboxChips ref={anchor} className="w-full">
                <ComboboxValue>
                    {(values) => (
                        <>
                            {(values as string[]).map((id) => (
                                <ComboboxChip key={id} title={labels[id] ?? id}>
                                    {labels[id] ?? id}
                                </ComboboxChip>
                            ))}
                            <ComboboxChipsInput placeholder={placeholder} disabled={disabled} />
                        </>
                    )}
                </ComboboxValue>
            </ComboboxChips>
            <ComboboxContent anchor={anchor}>
                <ComboboxEmpty>No matching channels</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item}>
                            {labels[item] ?? item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </>
    )
}

function LabeledIdCombobox({
    options,
    value,
    onChange,
    placeholder,
    disabled,
}: {
    options: { id: string; label: string }[]
    value: string | null
    onChange: (next: string | null) => void
    placeholder: string
    disabled?: boolean
}): JSX.Element {
    const labels = Object.fromEntries(options.map((option) => [option.id, option.label]))
    const items = options.map((option) => option.id)
    return (
        <Combobox items={items} value={value} onValueChange={(next: string | null) => onChange(next ?? null)}>
            <ComboboxInput placeholder={placeholder} disabled={disabled} showClear={!!value} className="w-full" />
            <ComboboxContent>
                <ComboboxEmpty>No matching channels</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => (
                        <ComboboxItem key={item} value={item}>
                            {labels[item] ?? item}
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
