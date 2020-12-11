import React, { useState } from 'react'
import { Tabs, Col, Row, Button, Spin } from 'antd'
import { Loading } from 'lib/utils'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic } from './insightHistoryLogic'
import { DashboardItemType } from '~/types'
import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import './insightHistoryPanel.scss'
import moment from 'moment'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'

const InsightHistoryType = {
    SAVED: 'SAVED',
    RECENT: 'RECENT',
    TEAM: 'TEAM',
}

const { TabPane } = Tabs

interface InsightHistoryPanelProps {
    onChange: () => void
}

function InsightPane({
    data,
    loading,
    loadMore,
    loadingMore,
    footer,
}: {
    data: DashboardItemType[]
    loading: boolean
    loadMore: CallableFunction
    loadingMore: boolean
    footer: (item: DashboardItemType) => JSX.Element
}): JSX.Element {
    const { loadTeamInsights, loadSavedInsights, loadInsights, updateInsight } = useActions(insightHistoryLogic)
    const { renameDashboardItem, duplicateDashboardItem } = useActions(dashboardItemsModel)

    return (
        <Row gutter={[16, 16]}>
            {loading && <Loading />}
            {data &&
                data.map((insight: DashboardItemType) => (
                    <Col xs={8} key={insight.id} style={{ height: 270 }}>
                        <DashboardItem
                            item={{ ...insight, color: undefined }}
                            key={insight.id + '_user'}
                            loadDashboardItems={() => {
                                loadInsights()
                                loadSavedInsights()
                                loadTeamInsights()
                            }}
                            saveDashboardItem={updateInsight}
                            renameDashboardItem={renameDashboardItem}
                            moveDashboardItem={(item: DashboardItemType, dashboardId: number) =>
                                duplicateDashboardItem(item, dashboardId)
                            }
                            preventLoading={true}
                            footer={<div className="dashboard-item-footer">{footer(insight)}</div>}
                        />
                    </Col>
                ))}
            <div
                style={{
                    textAlign: 'center',
                    margin: '12px auto',
                    height: 32,
                    lineHeight: '32px',
                }}
            >
                {loadingMore ? <Spin /> : <Button onClick={loadMore}>Load more</Button>}
            </div>
        </Row>
    )
}

export const InsightHistoryPanel: React.FC<InsightHistoryPanelProps> = () => {
    const {
        insights,
        insightsLoading,
        loadingMoreInsights,
        savedInsights,
        savedInsightsLoading,
        loadingMoreSavedInsights,
        teamInsights,
        teamInsightsLoading,
        loadingMoreTeamInsights,
    } = useValues(insightHistoryLogic)
    const { loadNextInsights, loadNextSavedInsights, loadNextTeamInsights } = useActions(insightHistoryLogic)

    const [activeTab, setActiveTab] = useState(InsightHistoryType.SAVED)

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
                    <InsightPane
                        data={insights.map((insight) => ({ ...insight, name: insight.name || 'Unsaved insight' }))}
                        loadMore={loadNextInsights}
                        loadingMore={loadingMoreInsights}
                        footer={(item) => <>Ran query {moment(item.created_at).fromNow()}</>}
                        loading={insightsLoading}
                    />
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Saved</span>}
                    key={InsightHistoryType.SAVED}
                    data-attr="insight-saved-pane"
                >
                    <InsightPane
                        data={savedInsights}
                        loadMore={loadNextSavedInsights}
                        loadingMore={loadingMoreSavedInsights}
                        footer={(item) => <>Saved {moment(item.created_at).fromNow()}</>}
                        loading={savedInsightsLoading}
                    />
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Team</span>}
                    key={InsightHistoryType.TEAM}
                    data-attr="insight-team-panel"
                >
                    <InsightPane
                        data={teamInsights}
                        loadMore={loadNextTeamInsights}
                        loadingMore={loadingMoreTeamInsights}
                        footer={(item) => (
                            <>
                                Saved {moment(item.created_at).fromNow()} by{' '}
                                {item.created_by?.first_name || item.created_by?.email || 'unknown'}
                            </>
                        )}
                        loading={teamInsightsLoading}
                    />
                </TabPane>
            </Tabs>
        </div>
    )
}
