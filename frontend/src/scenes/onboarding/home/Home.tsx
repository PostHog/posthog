import { PageHeader } from 'lib/components/PageHeader'
import React, { useEffect } from 'react'
import { LearnAndShare } from './sections/LearnAndShare'
import { TiledIconModule } from './sections/TiledIconModule'
import { DiscoverInsightsModule } from './sections/DiscoverInsight'
import { Layout, Space } from 'antd'
import { RocketOutlined } from '@ant-design/icons'
import './Home.scss'
import { useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { TileParams } from '~/types'
import { teamLogic } from 'scenes/teamLogic'

const { Content } = Layout

export function Home(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { reportProjectHomeSeen } = useActions(eventUsageLogic)

    const installationSources: TileParams[] = [
        {
            icon: <RocketOutlined />,
            title: 'Install PostHog',
            targetPath: '/ingestion',
            hoverText:
                'Our broad library support and simple API make it easy to install PostHog anywhere in your stack.',
            class: 'thumbnail-tile-install',
        },
    ]
    const installModule = (
        <TiledIconModule
            tiles={installationSources}
            analyticsModuleKey="install"
            header="Install PostHog"
            subHeader="Installation is easy. Choose from one of our libraries or our simple API."
        />
    )

    const layoutTeamHasEvents = (
        <>
            <DiscoverInsightsModule />
            <LearnAndShare />
        </>
    )

    const layoutTeamNeedsEvents = (
        <>
            {installModule}
            <LearnAndShare />
        </>
    )
    const teamHasData = currentTeam?.ingested_event

    useEffect(() => {
        reportProjectHomeSeen(teamHasData || false)
    }, [])

    return (
        <Layout className={'home-page'}>
            <div style={{ marginBottom: 128 }}>
                <Space direction="vertical">
                    <PageHeader
                        title="Home"
                        caption={
                            teamHasData ? undefined : 'Welcome to PostHog! Install one of our libraries to get started.'
                        }
                    />
                    <Content>
                        <Space direction="vertical">{teamHasData ? layoutTeamHasEvents : layoutTeamNeedsEvents}</Space>
                    </Content>
                </Space>
            </div>
        </Layout>
    )
}
