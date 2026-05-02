import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ApiSection } from './ApiSection'
import { EmailSection } from './EmailSection'
import { SlackSection } from './SlackSection'
import { supportSettingsLogic } from './supportSettingsLogic'
import { TeamsSection } from './TeamsSection'
import { WidgetSection } from './WidgetSection'

type ChannelTabKey = 'widget' | 'email' | 'slack' | 'teams' | 'api'

const DEFAULT_CHANNEL_TAB: ChannelTabKey = 'widget'

export function ChannelsSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { slackConnected, emailConnected, teamsConnected } = useValues(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { hashParams, searchParams } = useValues(router)
    const teamsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]

    const widgetEnabled = !!currentTeam?.conversations_settings?.widget_enabled
    const activeTab = (hashParams.channel as ChannelTabKey | undefined) ?? DEFAULT_CHANNEL_TAB

    const setTab = (tab: ChannelTabKey): void => {
        router.actions.replace(urls.supportSettings(), searchParams, { ...hashParams, channel: tab })
    }

    const channelTag = (connected: boolean): JSX.Element | null =>
        connected ? (
            <LemonTag type="success" size="small">
                On
            </LemonTag>
        ) : null

    return (
        <LemonTabs
            activeKey={activeTab}
            onChange={(key) => setTab(key)}
            tabs={[
                {
                    key: 'widget',
                    label: (
                        <span className="flex items-center gap-1.5">
                            Widget
                            {channelTag(widgetEnabled)}
                        </span>
                    ),
                    content: <WidgetSection />,
                },
                {
                    key: 'email',
                    label: (
                        <span className="flex items-center gap-1.5">
                            Email
                            {channelTag(emailConnected)}
                        </span>
                    ),
                    content: <EmailSection />,
                },
                {
                    key: 'slack',
                    label: (
                        <span className="flex items-center gap-1.5">
                            Slack
                            {channelTag(slackConnected)}
                        </span>
                    ),
                    content: <SlackSection />,
                },
                teamsEnabled && {
                    key: 'teams' as const,
                    label: (
                        <span className="flex items-center gap-1.5">
                            Microsoft Teams
                            {channelTag(teamsConnected)}
                        </span>
                    ),
                    content: <TeamsSection />,
                },
                {
                    key: 'api' as const,
                    label: (
                        <span className="flex items-center gap-1.5">
                            Direct API
                            {channelTag(true)}
                        </span>
                    ),
                    content: <ApiSection />,
                },
            ]}
        />
    )
}
