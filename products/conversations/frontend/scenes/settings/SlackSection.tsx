import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonDivider, LemonInput, LemonTag, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

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
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <SlackChannelSection />
            </LemonCard>
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
    } = useValues(supportSettingsLogic)
    const {
        connectSlack,
        setSlackChannels,
        loadSlackChannelsWithToken,
        setSlackTicketEmojiValue,
        saveSlackTicketEmoji,
        setSlackBotIconUrlValue,
        setSlackBotDisplayNameValue,
        saveSlackBotSettings,
        disconnectSlack,
    } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-col gap-y-2">
            <div>
                <label className="font-medium">Connection</label>
                <p className="text-xs text-muted-alt">
                    Install the SupportHog bot in your Slack workspace to enable support ticket creation from channels,
                    mentions, and emoji reactions. This is separate from the main PostHog Slack integration.
                </p>
                {!slackConnected && (
                    <LemonButton
                        className="mt-2"
                        type="primary"
                        size="small"
                        disabledReason={adminRestrictionReason}
                        onClick={() => connectSlack(window.location.pathname)}
                    >
                        Add SupportHog to Slack
                    </LemonButton>
                )}
            </div>
            {slackConnected && (
                <>
                    <LemonDivider />
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
                            <LemonInputSelect
                                mode="multiple"
                                value={slackChannelIds}
                                options={slackChannels.map((c: { id: string; name: string }) => ({
                                    key: c.id,
                                    label: `#${c.name}`,
                                }))}
                                onChange={(newValue: string[]) => setSlackChannels(newValue)}
                                loading={slackChannelsLoading}
                                placeholder="Select channels"
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={loadSlackChannelsWithToken}
                                disabledReason={slackChannelsLoading ? 'Loading channels...' : undefined}
                            >
                                Refresh
                            </LemonButton>
                        </div>
                    </div>
                    <LemonDivider />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Ticket emoji trigger</label>
                            <p className="text-xs text-muted-alt">
                                React with this emoji on any message to create a support ticket from it.
                            </p>
                        </div>
                        <div className="flex gap-2 items-center">
                            <LemonInput
                                value={slackTicketEmojiValue ?? slackTicketEmoji}
                                onChange={setSlackTicketEmojiValue}
                                placeholder="ticket"
                                className="max-w-[200px]"
                            />
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={saveSlackTicketEmoji}
                                disabledReason={!slackTicketEmojiValue ? 'Enter an emoji name' : undefined}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>
                    <LemonDivider />
                    <div className="flex flex-col gap-2">
                        <div>
                            <label className="font-medium">Bot appearance</label>
                            <p className="text-xs text-muted-alt">
                                Override the bot's display name and icon when posting messages. Leave blank to use
                                defaults. Requires the bot to be re-authorized if it was connected before this feature
                                was available.
                            </p>
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonInput
                                value={slackBotDisplayNameValue ?? slackBotDisplayName ?? ''}
                                onChange={setSlackBotDisplayNameValue}
                                placeholder="Display name (e.g. SupportHog)"
                                className="flex-1"
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <LemonInput
                                value={slackBotIconUrlValue ?? slackBotIconUrl ?? ''}
                                onChange={setSlackBotIconUrlValue}
                                placeholder="Icon URL (e.g. https://example.com/icon.png)"
                                className="flex-1"
                            />
                        </div>
                        <div>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={saveSlackBotSettings}
                                disabledReason={
                                    slackBotDisplayNameValue === null && slackBotIconUrlValue === null
                                        ? 'No changes to save'
                                        : undefined
                                }
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>
                    <LemonDivider />
                    <div className="flex items-center gap-4 justify-between">
                        <div>
                            <label className="font-medium">Bot mention</label>
                            <p className="text-xs text-muted-alt">
                                Users can @mention the bot in any channel to create a support ticket.
                            </p>
                        </div>
                        <LemonTag type="success">Active</LemonTag>
                    </div>
                    <LemonDivider />
                    <div className="flex justify-end">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            disabledReason={adminRestrictionReason}
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Remove SupportHog bot?',
                                    description:
                                        'This will stop creating tickets from Slack messages. Existing tickets will not be affected.',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Remove',
                                        onClick: disconnectSlack,
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        >
                            Remove SupportHog bot
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
