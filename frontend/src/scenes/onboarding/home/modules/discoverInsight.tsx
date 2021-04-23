import { useActions, useValues } from 'kea'
import { Avatar, Card, Carousel, CarouselProps, Divider, List, Space, Tooltip, Typography, Skeleton } from 'antd'
import {
    ArrowLeftOutlined,
    ArrowRightOutlined,
    FallOutlined,
    FieldTimeOutlined,
    FunnelPlotOutlined,
    LineChartOutlined,
    RightSquareOutlined,
    SlidersOutlined,
    TableOutlined,
} from '@ant-design/icons'
import React, { useEffect } from 'react'
import { DashboardItemType } from '~/types'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { DashboardItem, DisplayedType, displayMap } from 'scenes/dashboard/DashboardItem'
import { ViewType } from 'scenes/insights/insightLogic'
import { router } from 'kea-router'
import dayjs from 'dayjs'

const { Paragraph } = Typography

const insights = [
    {
        name: 'Trends',
        target: '/insights?insight=TRENDS',
        hint: "Answer questions like 'How many times does this event happen?'",
        description: 'desc',
        icon: <LineChartOutlined />,
    },
    {
        name: 'Funnels',
        description: 'desc',
        hint:
            "Answer questions like 'What percentage of users complete key steps?' and 'In which step are my users dropping-off?'",
        target: '/insights?insight=FUNNELS',
        icon: <FunnelPlotOutlined />,
    },
    {
        name: 'Sessions',
        description: 'desc',
        hint: 'Answer questions like how long do users spend in my product?',
        target: '/insights?insight=SESSIONS',
        icon: <FieldTimeOutlined />,
    },
    {
        name: 'Retention',
        description: 'desc',
        hint: "Answer questions like 'What percentage of users come back after X amount of days, weeks, months?'",
        target: '/insights?insight=RETENTION',
        icon: <TableOutlined />,
    },
    {
        name: 'Paths',
        description: 'desc',
        target: '/insights?insight=PATHS',
        icon: <RightSquareOutlined />,
    },
    {
        name: 'Stickiness',
        description: 'desc',
        target: '/insights?insight=STICKINESS',
        icon: <FallOutlined />,
    },
    {
        name: 'Lifecycle',
        description: 'desc',
        target: '/insights?insight=LIFECYCLE',
        icon: <SlidersOutlined />,
    },
]

function CreateAnalysisSection(): JSX.Element {
    return (
        <React.Fragment>
            <h3>Start an analysis</h3>
            <Paragraph>
                Each chart type is built to answer a specific kind of question. Hover over each to learn more about the
                kinds of questions it helps answer.
            </Paragraph>

            <List
                style={{ overflowY: 'scroll' }}
                grid={{}}
                dataSource={insights}
                renderItem={(insight) => (
                    <a href={insight.target}>
                        <Tooltip color={'#2d2d2d'} title={insight.hint ? insight.hint : 'no hint'}>
                            <List.Item className="insight-container" key={insight.name}>
                                <div>
                                    <Avatar
                                        size={100}
                                        shape={'square'}
                                        className={'thumbnail-tile-insights'}
                                        icon={insight.icon}
                                    >
                                        {insight.name}
                                    </Avatar>
                                    <h4 className={'insight-text'}>{insight.name}</h4>
                                </div>
                            </List.Item>
                        </Tooltip>
                    </a>
                )}
            />
        </React.Fragment>
    )
}

function InsightPane({
    data,
    loading,
    footer,
}: {
    data: DashboardItemType[]
    loading: boolean
    loadMore?: () => void
    loadingMore: boolean
    footer: (item: DashboardItemType) => JSX.Element
}): JSX.Element {
    const { loadTeamInsights, loadSavedInsights, loadInsights } = useActions(insightHistoryLogic)
    useEffect(() => {
        loadInsights()
        loadSavedInsights()
        loadTeamInsights()
    }, [])
    const settings: CarouselProps = {
        dots: true,
        slidesToShow: 4,
        slidesToScroll: 3,
        arrows: true,
        nextArrow: <ArrowRightOutlined />,
        prevArrow: <ArrowLeftOutlined />,
        vertical: false,
        centerMode: false,
        centerPadding: '10px',
        responsive: [
            {
                breakpoint: 1400,
                settings: {
                    vertical: false,
                    centerMode: true,
                    slidesToShow: 3,
                },
            },
            {
                breakpoint: 1000,
                settings: {
                    vertical: false,
                    centerMode: true,
                    slidesToShow: 2,
                },
            },

            {
                breakpoint: 700,
                settings: {
                    vertical: false,

                    centerMode: true,
                    slidesToShow: 1,
                },
            },
        ],
    }

    const thumbs = data.map((insight, idx) => (
        <Card key={idx} className={'insight-chart-tile'}>
            <DashboardItem
                item={{ ...insight, color: null }}
                key={idx}
                onClick={() => {
                    const _type: DisplayedType =
                        insight.filters.insight === ViewType.RETENTION ? 'RetentionContainer' : insight.filters.display
                    router.actions.push(displayMap[_type].link(insight))
                }}
                preventLoading={false}
                footer={<div className="dashboard-item-footer">{footer(insight)}</div>}
                index={idx}
                isOnEditMode={false}
            />
        </Card>
    ))
    data.length = 0
    return (
        <React.Fragment>
            <h3>Recent analyses across your team</h3>
            <Paragraph>Not sure where to start? Jump back into a recent analysis.</Paragraph>

            <Skeleton loading={loading}>
                {data.length > 0 && (
                    <React.Fragment>
                        <div className="team-insights-container">
                            <Carousel {...settings}>{thumbs}</Carousel>
                        </div>
                    </React.Fragment>
                )}

                {data.length <= 0 && (
                    <Space direction={'vertical'}>
                        <Paragraph style={{ marginTop: 5 }}>
                            It looks like there are no recent analyses. Time to get to work!
                        </Paragraph>
                    </Space>
                )}
            </Skeleton>
        </React.Fragment>
    )
}

export function DiscoverInsightsModule(): JSX.Element {
    const { insights, insightsLoading, loadingMoreInsights, savedInsights, teamInsights } = useValues(
        insightHistoryLogic
    )

    const orgInsights = [
        ...insights,
        ...savedInsights,
        // hack to filter out PostHog created insights – they introduce confusion since they aren't based on
        // project data.
        ...teamInsights.filter((insight) => insight.id > 7),
    ]
    return (
        <Card className="home-module-card">
            <h2 id="name" className="subtitle">
                Discover Insights
            </h2>
            <Divider />
            <Space direction={'vertical'}>
                <CreateAnalysisSection />
                <InsightPane
                    data={orgInsights.map((insight) => ({ ...insight }))}
                    loadingMore={loadingMoreInsights}
                    footer={(item) => <>Ran query {dayjs(item.created_at).fromNow()}</>}
                    // We only show module level spinners if insights are loading, team + saved insights take longer to compute
                    // and if any insights exist they should come back in the insights query.
                    // Each individual tile has it's own spinner if it isn't loaded yet.
                    loading={insightsLoading}
                />
            </Space>
        </Card>
    )
}
