import { Avatar, Card, Divider, Image, List, Spin, Typography, Collapse } from 'antd'
import React, { useState } from 'react'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/components/Tooltip'

const { Title } = Typography

const { Panel } = Collapse

import eventTrackingOverview from 'scenes/onboarding/home/static/event-tracking-overview.png'
import rollOutFeatures from 'scenes/onboarding/home/static/roll-out-features.png'
import analyzeConversions from 'scenes/onboarding/home/static/analyze-conversions.png'
import analyzeBehavior from 'scenes/onboarding/home/static/analyzing-behavior.png'
import measureRetention from 'scenes/onboarding/home/static/measure-retention.png'
import trackingSpas from 'scenes/onboarding/home/static/tracking-spas.png'
import salesRevenueTracking from 'scenes/onboarding/home/static/sales-revenue-tracking.png'
import trackingB2b from 'scenes/onboarding/home/static/tracking-b2b.png'
import trackingTeams from 'scenes/onboarding/home/static/tracking-teams.png'

import { TileParams } from '~/types'
import { GithubOutlined, SlackOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'

const UTM_TAGS = '?utm_medium=in-product&utm_campaign=project-home'

const LESSONS = [
    {
        title: 'Event Tracking Overview',
        hover: 'A complete guide to getting started with event tracking.',
        target: `https://posthog.com/docs/tutorials/actions${UTM_TAGS}`,
        imgSrc: eventTrackingOverview,
    },
    {
        title: 'Safely Roll Out New Features',
        hover: "A walk-through on how you can roll-out and learn from features using PostHog's feature flags.",
        target: `https://posthog.com/docs/tutorials/feature-flags?utm_content=project-homes${UTM_TAGS}`,
        imgSrc: rollOutFeatures,
    },
    {
        title: 'Funnels - Analyzing Conversions',
        hover: 'A walk-through on funnel analysis – a core component to learning about your product.',
        target: `https://posthog.com/docs/tutorials/funnels?utm_content=project-home${UTM_TAGS}`,
        imgSrc: analyzeConversions,
    },
    {
        title: 'Custom Behavioral Cohorts',
        hover:
            'A walk-through on how you can analyze sets of users in groups based on behaviors or properties that you define.',
        target: `https://posthog.com/docs/tutorials/cohorts?utm_content=project-home${UTM_TAGS}`,
        imgSrc: analyzeBehavior,
    },
    {
        title: 'Measuring Retention',
        hover: 'A walk-through on answering a question every company must ask itself: Are users coming back?',
        target: `https://posthog.com/docs/tutorials/retention?utm_content=project-home${UTM_TAGS}`,
        imgSrc: measureRetention,
    },
    {
        title: 'Tracking Single Page Applications',
        hover: 'Implement PostHog into single page applications such as AngularJS.',
        target: `https://posthog.com/docs/tutorials/spa${UTM_TAGS}`,
        imgSrc: trackingSpas,
    },
    {
        title: 'Revenue Tracking',
        hover: 'A guide on how you can use PostHog to track subscribers and revenue over time.',
        target: `https://posthog.com/docs/tutorials/revenue${UTM_TAGS}`,
        imgSrc: salesRevenueTracking,
    },

    {
        title: 'Tracking Key B2B Product Metrics',
        hover: 'A guide on how B2B companies can implement successful analytics strategies.',
        target: `https://posthog.com/docs/tutorials/b2b${UTM_TAGS}`,
        imgSrc: trackingB2b,
    },
    {
        title: 'Tracking Team Usage',
        hover: 'Track how organizations use your product.',
        target: `https://posthog.com/docs/tutorials/tracking-teams${UTM_TAGS}`,
        imgSrc: trackingTeams,
    },
]

function LessonsGrid(): JSX.Element {
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)

    const [isImageLoaded, setIsImageLoaded] = useState(false)
    return (
        <List
            style={{ height: 350, maxHeight: 350, overflowY: 'scroll' }}
            grid={{}}
            dataSource={LESSONS}
            renderItem={(lesson) => (
                <List.Item
                    className="lesson-list-item"
                    key={lesson.target}
                    onClick={() => {
                        reportProjectHomeItemClicked('tutorials', lesson.title, { lesson_url: lesson.target })
                    }}
                >
                    <Spin spinning={!isImageLoaded}>
                        <a href={lesson.target} target="_blank" rel="noreferrer noopener">
                            <Image
                                src={lesson.imgSrc}
                                onLoad={() => {
                                    setIsImageLoaded(true)
                                }}
                                width={250}
                                className="lesson-image"
                                preview={false}
                            />
                        </a>
                    </Spin>
                </List.Item>
            )}
        />
    )
}

export function CommunityIcons(): JSX.Element {
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)
    const tiles: TileParams[] = [
        {
            icon: <SlackOutlined />,
            title: 'Join us on Slack',
            targetPath: 'https://posthog.com/slack?s=app&utm_medium=in-product&utm_campaign=project-home',
            openInNewTab: true,
            hoverText:
                'Talk with other PostHog users, get support on issues, and exclusive access to features in beta development.',
        },
        {
            icon: <GithubOutlined />,
            title: 'Review our code',
            openInNewTab: true,
            targetPath: 'https://github.com/PostHog/posthog',
            hoverText: 'Submit a pull request and snag some PostHog merch!',
        },
    ]
    return (
        <List
            style={{ overflowY: 'scroll' }}
            grid={{}}
            dataSource={tiles}
            renderItem={(tile) => (
                <a
                    href={tile.targetPath}
                    target={tile.openInNewTab ? '_blank' : '_self'}
                    rel={tile.openInNewTab ? 'noopener' : ''}
                    onClick={() => {
                        reportProjectHomeItemClicked('community', tile.title)
                    }}
                >
                    <Tooltip placement="top" title={tile.hoverText ? tile.hoverText : ''}>
                        <List.Item className="insight-container" key={tile.title}>
                            <Avatar
                                size={55}
                                className={tile.class ? tile.class : 'thumbnail-tile-default'}
                                icon={tile.icon}
                            >
                                {tile.title}
                            </Avatar>
                            <h4 className={'insight-text'}>{tile.title}</h4>
                        </List.Item>
                    </Tooltip>
                </a>
            )}
        />
    )
}

export function LearnAndShare(): JSX.Element {
    const { user } = useValues(userLogic)
    const { insights, insightsLoading } = useValues(insightHistoryLogic)

    const COMMUNITY_PANEL = 'community'
    const TUTORIALS_PANEL = 'tutorials'

    // Workaround for an issue where Collapse does not re-render if the defaultActiveKey var updates
    const getShareAndLearnModule = (isActivatedUser: boolean): JSX.Element => {
        const activePanels = isActivatedUser ? [] : [COMMUNITY_PANEL, TUTORIALS_PANEL]
        return (
            <Collapse defaultActiveKey={activePanels} ghost>
                <Panel
                    forceRender={true}
                    header={
                        <Title level={5}>
                            Quick tutorials and exercises aimed at helping your team use product analytics
                        </Title>
                    }
                    key={TUTORIALS_PANEL}
                >
                    <Divider style={{ marginTop: -10 }} />

                    <LessonsGrid />
                </Panel>
                <Panel key={COMMUNITY_PANEL} header={<Title level={5}>Join our community</Title>}>
                    <Divider style={{ marginTop: -10 }} />
                    <CommunityIcons />
                </Panel>
            </Collapse>
        )
    }

    const showNewUserPanel = !insightsLoading && (!user?.team?.ingested_event || insights.length < 1)
    return (
        <Card className="home-page section-card">
            <Title level={4} id="name" className="subtitle">
                Learn and Share
            </Title>
            <Divider />
            {showNewUserPanel && getShareAndLearnModule(false)}
            {!showNewUserPanel && getShareAndLearnModule(true)}
        </Card>
    )
}
