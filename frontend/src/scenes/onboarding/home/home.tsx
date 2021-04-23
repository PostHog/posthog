import { PageHeader } from 'lib/components/PageHeader'
import React, { useState } from 'react'
import { PostHogLessons } from './modules/posthogLessons'
import { TiledIconModule, TileParams } from './modules/tiledIconModule'

import { DiscoverInsightsModule } from './modules/discoverInsight'
import { Button, Layout, Space, Tooltip } from 'antd'
import {
    SlackOutlined,
    RightSquareOutlined,
    LineChartOutlined,
    FunnelPlotOutlined,
    FieldTimeOutlined,
    TableOutlined,
    FallOutlined,
    SlidersOutlined,
    UserAddOutlined,
    RocketOutlined,
    GithubOutlined,
} from '@ant-design/icons'

import './home.scss'

const { Content } = Layout
import { useActions, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { router } from 'kea-router'
import { useAnchor } from 'lib/hooks/useAnchor'
import { CreateInviteModalWithButton } from 'scenes/organization/Settings/CreateInviteModal'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { userLogic } from 'scenes/userLogic'

function HeaderCTAs(): JSX.Element {
    const { setInviteMembersModalOpen } = useActions(navigationLogic)
    const { inviteMembersModalOpen } = useValues(navigationLogic)
    const { preflight } = useValues(preflightLogic)
    const [showToolTip, setShowToolTip] = useState(false)
    console.log(!inviteMembersModalOpen)
    const inviteModal = (
        <div>
            <Tooltip
                placement="bottom"
                visible={showToolTip && !inviteMembersModalOpen}
                title={"Because insights are better when they're shared with friends."}
            >
                <div>
                    {preflight?.email_service_available ? (
                        <Button
                            onMouseLeave={() => {
                                setShowToolTip(false)
                            }}
                            onMouseEnter={() => {
                                {
                                    setShowToolTip(true)
                                }
                            }}
                            type="primary"
                            icon={<UserAddOutlined />}
                            onClick={() => {
                                setInviteMembersModalOpen(true)
                            }}
                            data-attr="top-menu-invite-team-members"
                            style={{ width: '100%' }}
                        >
                            Invite Team Members
                        </Button>
                    ) : (
                        <CreateInviteModalWithButton
                            onMouseLeave={() => {
                                setShowToolTip(false)
                            }}
                            onMouseEnter={() => {
                                {
                                    setShowToolTip(true)
                                }
                            }}
                            block
                        />
                    )}
                </div>
            </Tooltip>
        </div>
    )

    return <Space direction={'vertical'}>{inviteModal}</Space>
}

export function Home(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { location } = useValues(router)

    const { user } = useValues(userLogic)
    useAnchor(location.hash)
    const installationSources: TileParams[] = [
        {
            icon: <RocketOutlined rotate={45} />,
            title: 'Install PostHog',
            targetPath: '/ingestion',
            hoverText: 'Installation is easy. Choose from one of our libraries or do it yourself using our simple API.',
        },
    ]
    const c = 'thumbnail-tile-community'
    const communitySources: TileParams[] = [
        {
            icon: <SlackOutlined />,
            title: 'Join Us in Slack',
            targetPath: 'https://posthog.com/slack?s=app',
            hoverText: '',
            class: c,
        },
        {
            icon: <GithubOutlined />,
            title: 'Checkout our GitHub',
            targetPath: 'https://github.com/PostHog/posthog',
            hoverText: 'Submit a PR and snag some PostHog merch!',
            class: c,
        },
    ]

    const insights: TileParams[] = [
        {
            title: 'Trends',
            targetPath: '/insights?insight=TRENDS',
            hoverText: "Answer questions like 'How many times does this event happen?'",
            icon: <LineChartOutlined />,
        },
        {
            title: 'Funnels',
            hoverText:
                "Answer questions like 'What percentage of users complete key steps?' and 'In which step are my users dropping-off?'",
            targetPath: '/insights?insight=FUNNELS',
            icon: <FunnelPlotOutlined />,
        },
        {
            title: 'Sessions',
            hoverText: 'Answer questions like how long do users spend in my product?',
            targetPath: '/insights?insight=SESSIONS',
            icon: <FieldTimeOutlined />,
        },
        {
            title: 'Retention',
            hoverText:
                "Answer questions like 'What percentage of users come back after X amount of days, weeks, months?'",
            targetPath: '/insights?insight=RETENTION',
            icon: <TableOutlined />,
        },
        {
            title: 'Paths',
            targetPath: '/insights?insight=PATHS',
            icon: <RightSquareOutlined />,
        },
        {
            title: 'Stickiness',
            targetPath: '/insights?insight=STICKINESS',
            icon: <FallOutlined />,
        },
        {
            title: 'Lifecycle',

            targetPath: '/insights?insight=LIFECYCLE',

            icon: <SlidersOutlined />,
        },
    ]
    const insightsClass = 'thumbnail-tile-insights'
    insights.forEach((insight) => {
        insight.class = insightsClass
    })

    const communityModule = (
        <TiledIconModule
            tiles={communitySources}
            header={'Join the PostHog Community'}
            subHeader={
                'Share your learnings with other PostHog users. Learn about the latest in product analytics directly from the PostHog team and members in our community.'
            }
        />
    )

    const lessonsModule = <PostHogLessons />
    const installModule = (
        <TiledIconModule
            tiles={installationSources}
            header="Install PostHog"
            subHeader="Installation is easy. Choose from one of our libraries or our simple API."
        />
    )

    const insightsModule = <DiscoverInsightsModule />
    const layoutTeamHasEvents = (
        <React.Fragment>
            {insightsModule}
            {lessonsModule}
            {communityModule}
        </React.Fragment>
    )

    const layoutTeamNeedsEvents = (
        <React.Fragment>
            {installModule}
            {communityModule}
            {lessonsModule}
        </React.Fragment>
    )

    return (
        <Layout>
            <div style={{ marginBottom: 128 }} className={'home-container'}>
                <Space direction="vertical">
                    <PageHeader
                        title={`${currentTeam?.name ?? ''} Project Home 🚀`}
                        caption={
                            !user?.team?.ingested_event
                                ? `Welcome to PostHog! Install one of our libraries to get started.`
                                : `Welcome back!`
                        }
                        buttons={HeaderCTAs()}
                    />
                    <Content>
                        <Space direction="vertical">
                            {!user?.team?.ingested_event ? layoutTeamNeedsEvents : layoutTeamHasEvents}
                        </Space>
                    </Content>
                </Space>
            </div>
        </Layout>
    )
}
