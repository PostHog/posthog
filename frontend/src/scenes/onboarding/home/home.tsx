import { PageHeader } from 'lib/components/PageHeader'
import React, { useState } from 'react'
import { PostHogLessons } from './modules/posthogLessons'
import { TiledIconModule, TileParams } from './modules/tiledIconModule'

import { DiscoverInsightsModule } from './modules/discoverInsight'
import { Button, Layout, Space, Tooltip } from 'antd'
import { SlackOutlined, UserAddOutlined, RocketOutlined, GithubOutlined } from '@ant-design/icons'

import './home.scss'

const { Content, Footer } = Layout
import { useActions, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { CreateInviteModalWithButton } from 'scenes/organization/Settings/CreateInviteModal'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { userLogic } from 'scenes/userLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

function HeaderCTAs(): JSX.Element {
    const { setInviteMembersModalOpen } = useActions(navigationLogic)
    const { inviteMembersModalOpen } = useValues(navigationLogic)
    const { preflight } = useValues(preflightLogic)
    const [showToolTip, setShowToolTip] = useState(false)

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
    const { user } = useValues(userLogic)
    const { reportProjectHomeSeen } = useActions(eventUsageLogic)

    const installationSources: TileParams[] = [
        {
            icon: <RocketOutlined rotate={45} />,
            title: 'Install PostHog',
            targetPath: '/ingestion',
            hoverText:
                'Our broad library support and simple API make it easy to install PostHog anywhere in your stack.',
            class: 'thumbnail-tile-install',
        },
    ]

    const communitySources: TileParams[] = [
        {
            icon: <SlackOutlined />,
            title: 'Hang out in Slack',
            targetPath: 'https://posthog.com/slack?s=app',
            openInNewTab: true,
            hoverText:
                'Talk with other PostHog users, get support on issues, and exclusive access to features in beta development.',
        },
        {
            icon: <GithubOutlined />,
            title: 'Clone our code',
            openInNewTab: true,
            targetPath: 'https://github.com/PostHog/posthog',
            hoverText: 'Submit a PR and snag some PostHog merch!',
        },
    ]

    const communityModule = (
        <TiledIconModule
            tiles={communitySources}
            analyticsModuleKey="community"
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
            analyticsModuleKey="install"
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
    const teamHasData = user?.team?.ingested_event
    reportProjectHomeSeen(teamHasData)
    return (
        <Layout>
            <div style={{ marginBottom: 128 }} className={'home-container'}>
                <Space direction="vertical">
                    <PageHeader
                        title={`${currentTeam?.name ?? ''} Project Home 🚀`}
                        caption={
                            !teamHasData ? `Welcome to PostHog! Install one of our libraries to get started.` : ` `
                        }
                        buttons={HeaderCTAs()}
                    />
                    <Content>
                        <Space direction="vertical">{teamHasData ? layoutTeamHasEvents : layoutTeamNeedsEvents}</Space>
                    </Content>
                </Space>
            </div>
            <Footer>
                <div>
                    <h5>
                        {`🦔 ❤ `} {currentTeam?.name ?? 'Your team'}
                    </h5>
                </div>
            </Footer>
        </Layout>
    )
}
