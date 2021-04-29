import { useActions, useValues } from 'kea'
import { Avatar, Card, Carousel, CarouselProps, Divider, List, Space, Tooltip, Typography, Skeleton, Spin } from 'antd'
import {
    FallOutlined,
    FieldTimeOutlined,
    FunnelPlotOutlined,
    LineChartOutlined,
    RightSquareOutlined,
    SlidersOutlined,
    TableOutlined,
} from '@ant-design/icons'
import React, { useEffect } from 'react'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { DashboardItem, DisplayedType, displayMap } from 'scenes/dashboard/DashboardItem'
import { ViewType } from 'scenes/insights/insightLogic'
import { router } from 'kea-router'
import dayjs from 'dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { CarouselArrow } from 'scenes/onboarding/home/sections/CarouselArrow'

const { Paragraph } = Typography

const insights = [
    {
        name: 'Trends',
        target: '/insights?insight=TRENDS',
        questions: [
            'How many users do we have?',
            'How many times do users perform specific events?',
            'When are my users most active?',
        ],
        icon: <LineChartOutlined />,
    },
    {
        name: 'Funnels',
        questions: [
            'What percent of users get through my sign up funnel?',
            'Where do my users experience the most friction?',
            'Which users make it to each step of a funnel?',
        ],
        target: '/insights?insight=FUNNELS',
        icon: <FunnelPlotOutlined />,
    },
    {
        name: 'Sessions',
        questions: ['How much time do users spend in our product?'],
        target: '/insights?insight=SESSIONS',
        icon: <FieldTimeOutlined />,
    },
    {
        name: 'Retention',
        questions: [
            'What percentage of users repeatedly use our product?',
            'How do different events impact how often users come back?',
        ],
        target: '/insights?insight=RETENTION',
        icon: <TableOutlined />,
    },
    {
        name: 'Paths',
        target: '/insights?insight=PATHS',
        questions: ['What actions are users taking as they navigate our product?'],
        icon: <RightSquareOutlined />,
    },
    {
        name: 'Stickiness',
        questions: ['How many times do users typically perform an action within a selected time period?'],
        target: '/insights?insight=STICKINESS',
        icon: <FallOutlined />,
    },
    {
        name: 'Lifecycle',
        target: '/insights?insight=LIFECYCLE',
        questions: ['How many users are we gaining, activating, and losing within a selected time period?'],
        icon: <SlidersOutlined />,
    },
]

const ANALYTICS_MODULE_KEY = 'insights'
function CreateAnalysisSection(): JSX.Element {
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)

    return (
        <div className={'home-page'}>
            <h3>Start an analysis</h3>
            <Paragraph>
                Each chart type is built to answer specific types of questions. Hover over each to learn more about the
                kinds of questions it can help answer.
            </Paragraph>

            <List
                style={{ overflowY: 'scroll' }}
                grid={{}}
                dataSource={insights}
                renderItem={(insight) => (
                    <a
                        href={insight.target}
                        onClick={() => {
                            reportProjectHomeItemClicked(ANALYTICS_MODULE_KEY, insight.name.toLowerCase())
                        }}
                    >
                        <Tooltip
                            color="var(--bg-charcoal)"
                            title={insight.questions.map((question, idx) => (
                                <Paragraph
                                    style={{ color: 'var(--text-light', padding: '3px' }}
                                    key={`${insight.name}_${idx}`}
                                >
                                    {`•` + question}
                                </Paragraph>
                            ))}
                        >
                            <List.Item className="insight-container" key={insight.name}>
                                <div>
                                    <Avatar
                                        size={100}
                                        shape={'square'}
                                        className={'thumbnail-tile-default'}
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
        </div>
    )
}

function InsightPane(): JSX.Element {
    const { loadInsights } = useActions(insightHistoryLogic)
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)
    const { insights, insightsLoading } = useValues(insightHistoryLogic)

    useEffect(() => {
        loadInsights()
    }, [])

    const settings: CarouselProps = {
        dots: true,
        slidesToShow: 4,
        slidesToScroll: 3,
        arrows: true,
        nextArrow: <CarouselArrow direction="next" />,
        prevArrow: <CarouselArrow direction="prev" />,
        vertical: false,
        centerMode: false,
        centerPadding: '10px',
        responsive: [
            {
                breakpoint: 1200,
                settings: {
                    vertical: false,
                    slidesToShow: 3,
                    centerPadding: '5px',
                },
            },
            {
                breakpoint: 1000,
                settings: {
                    vertical: false,
                    slidesToShow: 2,
                    slidesToScroll: 2,
                },
            },
            {
                breakpoint: 700,
                settings: {
                    vertical: false,
                    slidesToShow: 1,
                    slidesToScroll: 1,
                },
            },
        ],
    }

    return (
        <React.Fragment>
            <h3>Recent analyses across your team</h3>
            <Paragraph>Not sure where to start? Jump back into a recent analysis.</Paragraph>

            <Spin spinning={insightsLoading}>
                <Skeleton loading={insightsLoading}>
                    {insights.length > 0 && (
                        <React.Fragment>
                            <div className="carousel-container">
                                <Carousel {...settings}>
                                    {insights.map((insight, idx) => (
                                        <Card key={insight.id} bordered={false} className={'insight-chart-tile'}>
                                            <DashboardItem
                                                item={{ ...insight, color: null }}
                                                key={insight.id}
                                                onClick={() => {
                                                    reportProjectHomeItemClicked(
                                                        ANALYTICS_MODULE_KEY,
                                                        'recent analysis',
                                                        { insight_type: insight.filters.insight }
                                                    )
                                                    const _type: DisplayedType =
                                                        insight.filters.insight === ViewType.RETENTION
                                                            ? 'RetentionContainer'
                                                            : insight.filters.display
                                                    router.actions.push(displayMap[_type].link(insight))
                                                }}
                                                preventLoading={false}
                                                footer={
                                                    <div className="dashboard-item-footer">
                                                        {<>Ran query {dayjs(insight.created_at).fromNow()}</>}
                                                    </div>
                                                }
                                                index={idx}
                                                isOnEditMode={false}
                                            />
                                        </Card>
                                    ))}
                                </Carousel>
                            </div>
                        </React.Fragment>
                    )}

                    {!insightsLoading && insights.length === 0 && (
                        <Space direction={'vertical'}>
                            <Paragraph style={{ marginTop: 5 }}>
                                There are no recent analyses. Time to get to work!
                            </Paragraph>
                        </Space>
                    )}
                </Skeleton>
            </Spin>
        </React.Fragment>
    )
}

export function DiscoverInsightsModule(): JSX.Element {
    return (
        <Card className="home-page section-card">
            <h2 id="name" className="subtitle">
                Discover Insights
            </h2>
            <Divider />
            <Space direction={'vertical'} className={'home-page'}>
                <CreateAnalysisSection />
                <InsightPane />
            </Space>
        </Card>
    )
}
