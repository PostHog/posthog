import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronRight, IconCode } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { channelIcon } from '../Channels/ChannelsTag'
import { type SupportSetupChannel, supportSetupCardLogic } from './supportSetupCardLogic'

const COPY: Record<ProductEmptyStateMode, { title: string; lead: string }> = {
    'needs-setup': {
        title: 'Choose how customers reach you',
        lead: 'Picking a channel turns Support on and opens its setup. You can add more channels later.',
    },
    'waiting-for-data': {
        title: 'Connect a channel',
        lead: 'Tickets arrive from every channel you connect. You can use more than one.',
    },
}

interface SetupChannel {
    key: SupportSetupChannel
    icon: JSX.Element
    title: string
    description: string
    connected: boolean
}

/**
 * The Support empty state's setup card: one row per channel a ticket can arrive on, each
 * opening that channel's tab in Support settings.
 */
export function SupportSetupCard({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { pendingChannel } = useValues(supportSetupCardLogic)
    const { pickChannel } = useActions(supportSetupCardLogic)

    const supportEnabled = !!currentTeam?.conversations_enabled
    const settings = currentTeam?.conversations_settings

    const channels: SetupChannel[] = [
        {
            key: 'widget',
            icon: channelIcon.widget,
            title: 'Widget',
            description: 'Add a chat bubble to your website or app.',
            connected: !!settings?.widget_enabled,
        },
        {
            key: 'email',
            icon: channelIcon.email,
            title: 'Email',
            description: 'Receive and answer emails sent to your support address.',
            connected: !!settings?.email_enabled,
        },
        {
            key: 'slack',
            icon: channelIcon.slack,
            title: 'Slack',
            description: 'Turn Slack messages into tickets.',
            connected: !!settings?.slack_enabled,
        },
        ...(featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]
            ? [
                  {
                      key: 'teams' as const,
                      icon: channelIcon.teams,
                      title: 'Microsoft Teams',
                      description: 'Turn Teams messages into tickets.',
                      connected: !!settings?.teams_enabled,
                  },
              ]
            : []),
        {
            key: 'api',
            icon: <IconCode />,
            title: 'Direct API',
            description: 'Send tickets from your own contact form or custom UI.',
            // The API has no switch of its own, so it has no connected state to report.
            connected: false,
        },
    ]

    return (
        <div className="mt-2 flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="flex flex-col gap-1 px-4 pb-3 pt-3.5">
                <span className="text-base font-semibold">{COPY[mode].title}</span>
                <span className="text-sm text-secondary">{COPY[mode].lead}</span>
            </div>
            <div className="flex flex-col gap-px border-t border-primary p-1">
                {channels.map((channel) => (
                    <LemonButton
                        key={channel.key}
                        fullWidth
                        icon={channel.icon}
                        sideIcon={<IconChevronRight className="size-3" />}
                        loading={pendingChannel === channel.key}
                        disabledReason={
                            pendingChannel && pendingChannel !== channel.key ? 'Turning Support on…' : undefined
                        }
                        onClick={() => pickChannel(channel.key, mode, preview)}
                        data-attr={`support-setup-channel-${channel.key}`}
                    >
                        <span className="flex min-w-0 flex-col py-0.5 text-left">
                            <span className="flex items-center gap-1.5 font-semibold">
                                {channel.title}
                                {supportEnabled && channel.connected ? (
                                    <LemonTag type="success" size="small">
                                        On
                                    </LemonTag>
                                ) : null}
                            </span>
                            <span className="whitespace-normal text-xs font-normal text-secondary">
                                {channel.description}
                            </span>
                        </span>
                    </LemonButton>
                ))}
            </div>
            {/* The imports tab in Support settings only exists once Support is on. */}
            {supportEnabled ? (
                <div className="border-t border-primary px-4 py-2.5 text-xs text-secondary">
                    Moving from Zendesk?{' '}
                    <Link
                        to={combineUrl(urls.supportSettings(), {}, { selectedSetting: 'conversations-imports' }).url}
                        data-attr="support-setup-zendesk-import"
                    >
                        Import your tickets
                    </Link>
                </div>
            ) : null}
        </div>
    )
}
