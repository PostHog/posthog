import { useValues } from 'kea'

import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { type ChannelTabKey, openChannelSettings } from '../../scenes/settings/openChannelSettings'
import { supportSettingsLogic } from '../../scenes/settings/supportSettingsLogic'
import { QuillChannelStatusList } from '../QuillChannelStatusList/QuillChannelStatusList'

export function ChannelStatusList(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { slackConnected, emailConnected, teamsConnected, githubConnected } = useValues(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const channels: { key: ChannelTabKey; label: string; on: boolean; available: boolean }[] = [
        {
            key: 'widget',
            label: 'Widget',
            on: !!currentTeam?.conversations_settings?.widget_enabled,
            available: true,
        },
        { key: 'email', label: 'Email', on: emailConnected, available: true },
        { key: 'slack', label: 'Slack', on: slackConnected, available: true },
        {
            key: 'teams',
            label: 'Microsoft Teams',
            on: teamsConnected,
            available: !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED],
        },
        {
            key: 'github',
            label: 'GitHub',
            on: githubConnected,
            available: !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_GITHUB_CHANNEL],
        },
        { key: 'api', label: 'Direct API', on: true, available: true },
    ]

    const availableChannels = channels.filter((channel) => channel.available)

    if (todayRailNav) {
        return <QuillChannelStatusList channels={availableChannels} onOpenChannel={openChannelSettings} />
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col max-w-[800px] px-4 py-1 divide-y">
            {availableChannels.map((channel) => (
                <div key={channel.key} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span className="flex items-center gap-2 font-medium">
                        {channel.label}
                        <LemonTag type={channel.on ? 'success' : 'default'} size="small">
                            {channel.on ? 'On' : 'Off'}
                        </LemonTag>
                    </span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => openChannelSettings(channel.key)}
                        data-attr={`support-general-channel-${channel.key}`}
                    >
                        {channel.on ? 'Manage' : 'Set up'}
                    </LemonButton>
                </div>
            ))}
        </LemonCard>
    )
}
