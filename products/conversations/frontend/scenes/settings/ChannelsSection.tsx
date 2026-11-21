import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTab, LemonTabs, LemonTag } from '@posthog/lemon-ui'
import { Badge, Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ApiSection } from './ApiSection'
import { EmailSection } from './EmailSection'
import { GithubSection } from './GithubSection'
import { type ChannelTabKey } from './openChannelSettings'
import { SlackSection } from './SlackSection'
import { supportSettingsLogic } from './supportSettingsLogic'
import { TeamsSection } from './TeamsSection'
import { WidgetSection } from './WidgetSection'

const DEFAULT_CHANNEL_TAB: ChannelTabKey = 'widget'

export function ChannelsSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { slackConnected, emailConnected, teamsConnected, githubConnected } = useValues(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { hashParams, searchParams } = useValues(router)
    const teamsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]
    const githubEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_GITHUB_CHANNEL]
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const widgetEnabled = !!currentTeam?.conversations_settings?.widget_enabled
    const activeTab = (hashParams.channel as ChannelTabKey | undefined) ?? DEFAULT_CHANNEL_TAB

    const setTab = (tab: ChannelTabKey): void => {
        router.actions.replace(urls.supportSettings(), searchParams, { ...hashParams, channel: tab })
    }

    const channelTag = (connected: boolean): JSX.Element | null =>
        connected ? (
            todayRailNav ? (
                <Badge variant="success">On</Badge>
            ) : (
                <LemonTag type="success" size="small">
                    On
                </LemonTag>
            )
        ) : null

    const tabs: (LemonTab<ChannelTabKey> | false)[] = [
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
        githubEnabled && {
            key: 'github' as const,
            label: (
                <span className="flex items-center gap-1.5">
                    GitHub
                    {channelTag(githubConnected)}
                </span>
            ),
            content: <GithubSection />,
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
    ]

    if (todayRailNav) {
        const visibleTabs = tabs.filter((tab): tab is LemonTab<ChannelTabKey> => !!tab)

        return (
            <Tabs value={activeTab} onValueChange={(key) => setTab(key as ChannelTabKey)}>
                <TabsList variant="line" className="max-w-full flex-wrap justify-start">
                    {visibleTabs.map((tab) => (
                        <TabsTrigger key={tab.key} value={tab.key}>
                            {tab.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
                {visibleTabs.map((tab) => (
                    <TabsContent key={tab.key} value={tab.key}>
                        {'content' in tab ? tab.content : null}
                    </TabsContent>
                ))}
            </Tabs>
        )
    }

    return <LemonTabs activeKey={activeTab} onChange={(key) => setTab(key)} tabs={tabs} />
}
