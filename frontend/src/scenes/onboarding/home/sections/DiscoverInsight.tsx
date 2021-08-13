import { useActions, useValues } from 'kea'
import { Avatar, Card, Divider, List, Typography, Collapse } from 'antd'
import { Tooltip } from 'lib/components/Tooltip'

const { Panel } = Collapse

const { Title } = Typography
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

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { InsightHistoryPanel } from 'scenes/insights/InsightHistoryPanel'

const { Paragraph } = Typography

const insightsTypes = [
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
            <Collapse defaultActiveKey="create-analysis" ghost>
                <Panel key="create-analysis" header={<Title level={5}>Start an analysis</Title>}>
                    <Card bordered={false} style={{ marginTop: -30 }} size="small">
                        <Divider />
                        <Paragraph>
                            Each chart type is built to answer specific types of questions. Hover over each chart to
                            learn more.
                        </Paragraph>
                        <List
                            style={{ overflowY: 'scroll', marginBottom: -20 }}
                            grid={{}}
                            dataSource={insightsTypes}
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
                                                style={{ color: 'var(--text-light)', padding: '3px' }}
                                                key={`${insight.name}_${idx}`}
                                            >
                                                {`•` + question}
                                            </Paragraph>
                                        ))}
                                    >
                                        <List.Item className="insight-container" key={insight.name}>
                                            <div>
                                                <Avatar
                                                    size={60}
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
                    </Card>
                </Panel>
            </Collapse>
        </div>
    )
}

function RecentInsightList(): JSX.Element {
    return (
        <>
            <Collapse defaultActiveKey={'team-analyses'} ghost>
                <Panel
                    forceRender={true}
                    key={'team-analyses'}
                    header={
                        <>
                            <Title level={5}>Recent analyses across your team</Title>
                        </>
                    }
                >
                    <React.Fragment>
                        <Card className="history-panel-container" bordered={false} style={{ marginTop: '-30px' }}>
                            <Divider />
                            <Paragraph>Jump back into recent work or an analysis from one of your teammates.</Paragraph>

                            <InsightHistoryPanel displayLocation="project home" />
                        </Card>
                    </React.Fragment>
                </Panel>
            </Collapse>
        </>
    )
}

export function DiscoverInsightsModule(): JSX.Element {
    const { insights, teamInsights, savedInsights } = useValues(insightHistoryLogic)
    const { loadInsights, loadTeamInsights, loadSavedInsights } = useActions(insightHistoryLogic)

    useEffect(() => {
        loadInsights()
        loadTeamInsights()
        loadSavedInsights()
    }, [])

    return (
        <Card className="home-page section-card">
            <Title level={4} id="name" className="subtitle">
                Discover Insights
            </Title>
            <Divider />
            <CreateAnalysisSection />
            {(insights.length > 0 || teamInsights.length > 0 || savedInsights.length > 0) && <RecentInsightList />}
        </Card>
    )
}
