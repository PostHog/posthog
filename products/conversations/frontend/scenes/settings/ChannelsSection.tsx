import { useValues } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Badge, Tabs, TabsList, TabsTrigger } from 'lib/ui/quill'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ApiSection } from './ApiSection'
import { EmailSection } from './EmailSection'
import { GithubSection } from './GithubSection'
import { SlackSection } from './SlackSection'
import { supportSettingsLogic } from './supportSettingsLogic'
import { TeamsSection } from './TeamsSection'
import { WidgetSection } from './WidgetSection'

type ChannelTabKey = 'widget' | 'email' | 'slack' | 'teams' | 'github' | 'api'

const DEFAULT_CHANNEL_TAB: ChannelTabKey = 'widget'

function ChannelOnBadge({ connected }: { connected: boolean }): JSX.Element | null {
    return connected ? <Badge variant="success">On</Badge> : null
}

export function ChannelsSection(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { slackConnected, emailConnected, teamsConnected, githubConnected } = useValues(supportSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { hashParams, searchParams } = useValues(router)
    const teamsEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]
    const githubEnabled = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_GITHUB_CHANNEL]

    const widgetEnabled = !!currentTeam?.conversations_settings?.widget_enabled
    const activeTab = (hashParams.channel as ChannelTabKey | undefined) ?? DEFAULT_CHANNEL_TAB

    const setTab = (tab: ChannelTabKey): void => {
        router.actions.replace(urls.supportSettings(), searchParams, { ...hashParams, channel: tab })
    }

    return (
        <div className="flex flex-col gap-3">
            <Tabs value={activeTab} onValueChange={(key) => setTab(key as ChannelTabKey)}>
                <TabsList variant="line">
                    <TabsTrigger value="widget">
                        <span className="flex items-center gap-1.5">
                            Widget
                            <ChannelOnBadge connected={widgetEnabled} />
                        </span>
                    </TabsTrigger>
                    <TabsTrigger value="email">
                        <span className="flex items-center gap-1.5">
                            Email
                            <ChannelOnBadge connected={emailConnected} />
                        </span>
                    </TabsTrigger>
                    <TabsTrigger value="slack">
                        <span className="flex items-center gap-1.5">
                            Slack
                            <ChannelOnBadge connected={slackConnected} />
                        </span>
                    </TabsTrigger>
                    {teamsEnabled ? (
                        <TabsTrigger value="teams">
                            <span className="flex items-center gap-1.5">
                                Microsoft Teams
                                <ChannelOnBadge connected={teamsConnected} />
                            </span>
                        </TabsTrigger>
                    ) : null}
                    {githubEnabled ? (
                        <TabsTrigger value="github">
                            <span className="flex items-center gap-1.5">
                                GitHub
                                <ChannelOnBadge connected={githubConnected} />
                            </span>
                        </TabsTrigger>
                    ) : null}
                    <TabsTrigger value="api">
                        <span className="flex items-center gap-1.5">
                            Direct API
                            <ChannelOnBadge connected={true} />
                        </span>
                    </TabsTrigger>
                </TabsList>
            </Tabs>
            {activeTab === 'widget' ? <WidgetSection /> : null}
            {activeTab === 'email' ? <EmailSection /> : null}
            {activeTab === 'slack' ? <SlackSection /> : null}
            {teamsEnabled && activeTab === 'teams' ? <TeamsSection /> : null}
            {githubEnabled && activeTab === 'github' ? <GithubSection /> : null}
            {activeTab === 'api' ? <ApiSection /> : null}
        </div>
    )
}
