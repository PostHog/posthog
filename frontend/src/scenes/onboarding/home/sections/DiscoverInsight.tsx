import { useActions, useValues } from 'kea'
import { Avatar, Card, Carousel, CarouselProps, Divider, List, Space, Tooltip, Typography, Skeleton, Spin } from 'antd'
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
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { DashboardItem, DisplayedType, displayMap } from 'scenes/dashboard/DashboardItem'
import { ViewType } from 'scenes/insights/insightLogic'
import { router } from 'kea-router'
import dayjs from 'dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

const { Paragraph } = Typography

const insights = [
    {
        name: 'Trends',
        target: '/insights?insight=TRENDS',
        questions: [
            'How many active users do we have?',
            'How many times do users perform specific events?',
            'When are my users most active?',
        ],
        icon: <LineChartOutlined />,
    },
    {
        name: 'Funnels',
        questions: [
            'What percent of users get through my sign up funnel?',
            'Where do most of my users experience the most friction?',
            'Which users complete some steps but not others?',
        ],
        target: '/insights?insight=FUNNELS',
        icon: <FunnelPlotOutlined />,
    },
    {
        name: 'Sessions',
        questions: ["How much time do users spend when they're using our product?"],
        target: '/insights?insight=SESSIONS',
        icon: <FieldTimeOutlined />,
    },
    {
        name: 'Retention',
        questions: [
            'What percentage of users continue to use our product?',
            'How do different events correlate to more users returning?',
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
        questions: ['How often are users repeating specific events across subsequent time periods?'],
        target: '/insights?insight=STICKINESS',
        icon: <FallOutlined />,
    },
    {
        name: 'Lifecycle',
        target: '/insights?insight=LIFECYCLE',
        questions: ['How many users are you losing, re-engaging, activating, and acquiring across time periods?'],
        icon: <SlidersOutlined />,
    },
]

const ANALYTICS_MODULE_KEY = 'insights'
function CreateAnalysisSection(): JSX.Element {
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)

    return (
        <React.Fragment>
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
                            color="var(--primary-alt)"
                            title={insight.questions.map((question, idx) => (
                                <Paragraph className={'insight-tooltip'} key={idx}>
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
        </React.Fragment>
    )
}

function InsightPane(): JSX.Element {
    const { loadTeamInsights, loadSavedInsights, loadInsights } = useActions(insightHistoryLogic)
    const { reportProjectHomeItemClicked } = useActions(eventUsageLogic)
    const { insights, insightsLoading } = useValues(insightHistoryLogic)
    useEffect(() => {
        loadInsights()
        loadSavedInsights()
        loadTeamInsights()
    }, [])
    const settings: CarouselProps = {
        dots: true,
        slidesToShow: 5,
        slidesToScroll: 3,
        arrows: true,
        nextArrow: <ArrowRightOutlined />,
        prevArrow: <ArrowLeftOutlined />,
        vertical: false,
        centerMode: false,
        centerPadding: '10px',
        responsive: [
            {
                breakpoint: 2000,
                settings: {
                    vertical: false,
                    slidesToShow: 4,
                },
            },
            {
                breakpoint: 1400,
                settings: {
                    vertical: false,
                    slidesToShow: 3,
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
    const data = [...insights]

    return (
        <React.Fragment>
            <h3>Recent analyses across your team</h3>
            <Paragraph>Not sure where to start? Jump back into a recent analysis.</Paragraph>

            <Spin spinning={insightsLoading}>
                <Skeleton loading={insightsLoading}>
                    {data.length > 0 && (
                        <React.Fragment>
                            <div className="home-module-carousel-container">
                                <Carousel {...settings}>
                                    {data.map((insight, idx) => (
                                        <Card key={idx} bordered={false} className={'insight-chart-tile'}>
                                            <DashboardItem
                                                item={{ ...insight, color: null }}
                                                key={idx}
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

                    {data.length <= 0 && (
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
        <Card className="home-module-card">
            <h2 id="name" className="subtitle">
                Discover Insights
            </h2>
            <Divider />
            <Space direction={'vertical'}>
                <CreateAnalysisSection />
                <InsightPane />
            </Space>
        </Card>
    )
}
