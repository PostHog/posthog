import React, { useState } from 'react'
import { Tabs, Button, List, Col, Spin, Row, Tooltip } from 'antd'
import { toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { PushpinOutlined, PushpinFilled } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic } from './insightHistoryLogic'
import { InsightHistory } from '~/types'
import SaveModal from '../SaveModal'
import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import './insightHistoryPanel.scss'
import moment from 'moment'

const InsightHistoryType = {
    SAVED: 'SAVED',
    RECENT: 'RECENT',
    TEAM: 'TEAM',
}

const { TabPane } = Tabs

interface InsightHistoryPanelProps {
    onChange: () => void
}

export const InsightHistoryPanel: React.FC<InsightHistoryPanelProps> = ({ onChange }: InsightHistoryPanelProps) => {
    const {
        insights,
        insightsLoading,
        savedInsights,
        teamInsights,
        teamInsightsLoading,
        insightsNext,
        teamInsightsNext,
        loadingMoreInsights,
        loadingMoreTeamInsights,
    } = useValues(insightHistoryLogic)
    const { saveInsight, loadNextInsights, loadNextTeamInsights } = useActions(insightHistoryLogic)

    const [visible, setVisible] = useState(false)
    const [activeTab, setActiveTab] = useState(InsightHistoryType.SAVED)
    const [selectedInsight, setSelectedInsight] = useState<InsightHistory | null>(null)

    const loadMoreInsights = insightsNext ? (
        <div
            style={{
                textAlign: 'center',
                marginTop: 12,
                height: 32,
                lineHeight: '32px',
            }}
        >
            {loadingMoreInsights ? <Spin /> : <Button onClick={loadNextInsights}>Load more</Button>}
        </div>
    ) : null

    // const loadMoreSavedInsights = savedInsightsNext ? (
    //     <div
    //         style={{
    //             textAlign: 'center',
    //             marginTop: 12,
    //             height: 32,
    //             lineHeight: '32px',
    //         }}
    //     >
    //         {loadingMoreSavedInsights ? <Spin /> : <Button onClick={loadNextSavedInsights}>Load more</Button>}
    //     </div>
    // ) : null

    const loadMoreTeamInsights = teamInsightsNext ? (
        <div
            style={{
                textAlign: 'center',
                marginTop: 12,
                height: 32,
                lineHeight: '32px',
            }}
        >
            {loadingMoreTeamInsights ? <Spin /> : <Button onClick={loadNextTeamInsights}>Load more</Button>}
        </div>
    ) : null

    return (
        <div data-attr="insight-history-panel" className="insight-history-panel">
            <Tabs
                style={{
                    overflow: 'visible',
                }}
                animated={false}
                activeKey={activeTab}
                onChange={(activeKey: string): void => setActiveTab(activeKey)}
            >
                <TabPane
                    tab={<span data-attr="insight-history-tab">Recent</span>}
                    key={InsightHistoryType.RECENT}
                    data-attr="insight-history-pane"
                >
                    <List
                        loading={insightsLoading}
                        dataSource={insights}
                        loadMore={loadMoreInsights}
                        renderItem={(insight: InsightHistory) => {
                            return (
                                <List.Item>
                                    <Col style={{ whiteSpace: 'pre-line', width: '100%' }}>
                                        <Row justify="space-between" align="middle">
                                            {insight.filters.insight && (
                                                <Link onClick={onChange} to={'/insights?' + toParams(insight.filters)}>
                                                    {insight.filters.insight.charAt(0).toUpperCase() +
                                                        insight.filters.insight.slice(1).toLowerCase()}
                                                </Link>
                                            )}
                                            {insight.saved ? (
                                                <Tooltip
                                                    title="This configuration has already been saved"
                                                    placement="left"
                                                >
                                                    <PushpinFilled className="button-border" />
                                                </Tooltip>
                                            ) : (
                                                <Tooltip title="Save insight configuration" placement="left">
                                                    <PushpinOutlined
                                                        className="clickable button-border"
                                                        onClick={() => {
                                                            setVisible(true)
                                                            setSelectedInsight(insight)
                                                        }}
                                                        style={{ cursor: 'pointer' }}
                                                    />
                                                </Tooltip>
                                            )}
                                        </Row>
                                    </Col>
                                </List.Item>
                            )
                        }}
                    />
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Saved</span>}
                    key={InsightHistoryType.SAVED}
                    data-attr="insight-saved-pane"
                >
                    <Row gutter={[16, 16]}>
                        {savedInsights.map((insight: InsightHistory) => (
                            <Col xs={8} key={insight.id} style={{ height: 270 }}>
                                <DashboardItem
                                    item={insight}
                                    options={<div className="dashboard-item-settings">hi</div>}
                                    footer={
                                        <div className="dashboard-item-footer">
                                            Last saved {moment(insight.created_at).fromNow()}
                                        </div>
                                    }
                                />
                            </Col>
                        ))}
                    </Row>
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Team</span>}
                    key={InsightHistoryType.TEAM}
                    data-attr="insight-team-pane"
                >
                    <List
                        loading={teamInsightsLoading}
                        dataSource={teamInsights}
                        loadMore={loadMoreTeamInsights}
                        renderItem={(insight: InsightHistory) => {
                            return (
                                <List.Item key={insight.id}>
                                    <Col style={{ whiteSpace: 'pre-line', width: '100%' }}>
                                        <Row justify="space-between" align="middle">
                                            {insight.filters.insight && (
                                                <Link onClick={onChange} to={'/insights?' + toParams(insight.filters)}>
                                                    {insight.name}
                                                </Link>
                                            )}
                                        </Row>
                                    </Col>
                                </List.Item>
                            )
                        }}
                    />
                </TabPane>
            </Tabs>
            <SaveModal
                title="Save Chart"
                prompt="Name of Chart"
                textLabel="Name"
                textPlaceholder="DAUs Last 14 days"
                visible={visible}
                onCancel={(): void => {
                    setVisible(false)
                    setSelectedInsight(null)
                }}
                onSubmit={(text): void => {
                    if (selectedInsight) {
                        saveInsight(selectedInsight, text)
                    }
                    setVisible(false)
                    setSelectedInsight(null)
                }}
            />
        </div>
    )
}
