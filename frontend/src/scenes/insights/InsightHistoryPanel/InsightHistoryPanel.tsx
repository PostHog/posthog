import React, { useEffect, useState } from 'react'
import { Tabs, Col, Row, Button, Spin } from 'antd'
import { Loading } from 'lib/utils'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic } from './insightHistoryLogic'
import { DashboardItemType, ViewType } from '~/types'
import { DashboardItem, DisplayedType, displayMap } from 'scenes/dashboard/DashboardItem'
import './InsightHistoryPanel.scss'
import dayjs from 'dayjs'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { router } from 'kea-router'
import relativeTime from 'dayjs/plugin/relativeTime'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

dayjs.extend(relativeTime)

const InsightHistoryType = {
    SAVED: 'SAVED',
    RECENT: 'RECENT',
    TEAM: 'TEAM',
}

const { TabPane } = Tabs

interface InsightHistoryPanelProps {
    onChange?: () => void
    displayLocation?: string
}

function InsightPane({
    data,
    loading,
    loadMore,
    loadingMore,
    footer,
    reportOnClick,
}: {
    data: DashboardItemType[]
    loading: boolean
    loadMore?: () => void
    loadingMore: boolean
    footer: (item: DashboardItemType) => JSX.Element
    reportOnClick?: () => void
}): JSX.Element {
    const { loadTeamInsights, loadSavedInsights, loadInsights, updateInsight } = useActions(insightHistoryLogic)
    const { duplicateDashboardItem } = useActions(dashboardItemsModel)

    useEffect(() => {
        loadInsights()
        loadSavedInsights()
        loadTeamInsights()
    }, [])

    return (
        <Row gutter={[16, 16]}>
            {loading && <Loading />}
            {data &&
                data.map((insight: DashboardItemType, index: number) => (
                    <Col xs={24} sm={12} md={data.length > 1 ? 8 : 12} key={insight.id} style={{ height: 270 }}>
                        <DashboardItem
                            item={{ ...insight, color: null }}
                            key={insight.id + '_user'}
                            loadDashboardItems={() => {
                                loadInsights()
                                loadSavedInsights()
                                loadTeamInsights()
                            }}
                            saveDashboardItem={updateInsight}
                            dashboardMode={null}
                            onClick={() => {
                                if (reportOnClick) {
                                    reportOnClick()
                                }
                                const _type: DisplayedType =
                                    insight.filters.insight === ViewType.RETENTION
                                        ? 'RetentionContainer'
                                        : insight.filters.display
                                router.actions.push(displayMap[_type].link(insight))
                            }}
                            moveDashboardItem={
                                insight.saved
                                    ? (item: DashboardItemType, dashboardId: number) => {
                                          duplicateDashboardItem(item, dashboardId)
                                      }
                                    : undefined
                            }
                            preventLoading={true}
                            footer={<div className="dashboard-item-footer">{footer(insight)}</div>}
                            index={index}
                            isOnEditMode={false}
                        />
                    </Col>
                ))}
            {loadMore && (
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
            )}
        </Row>
    )
}

export const InsightHistoryPanel: React.FC<InsightHistoryPanelProps> = ({ displayLocation }) => {
    const {
        insights,
        insightsLoading,
        loadingMoreInsights,
        insightsNext,
        savedInsights,
        savedInsightsLoading,
        loadingMoreSavedInsights,
        savedInsightsNext,
        teamInsights,
        teamInsightsLoading,
        loadingMoreTeamInsights,
        teamInsightsNext,
    } = useValues(insightHistoryLogic)
    const { loadNextInsights, loadNextSavedInsights, loadNextTeamInsights } = useActions(insightHistoryLogic)
    const { reportInsightHistoryItemClicked } = useActions(eventUsageLogic)

    const [activeTab, setActiveTab] = useState(
        !insightsLoading && insights?.length < 3 && teamInsights?.length > insights?.length
            ? InsightHistoryType.TEAM
            : InsightHistoryType.RECENT
    )

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
                        data={insights.map((insight) => ({ ...insight }))}
                        loadMore={insightsNext ? loadNextInsights : undefined}
                        loadingMore={loadingMoreInsights}
                        footer={(item) => <>Ran query {dayjs(item.created_at).fromNow()}</>}
                        loading={insightsLoading}
                        reportOnClick={() => {
                            reportInsightHistoryItemClicked(InsightHistoryType.RECENT, displayLocation)
                        }}
                    />
                </TabPane>
                {savedInsights?.length > 0 && (
                    <TabPane
                        tab={<span data-attr="insight-saved-tab">Saved</span>}
                        key={InsightHistoryType.SAVED}
                        data-attr="insight-saved-pane"
                    >
                        <InsightPane
                            data={savedInsights}
                            loadMore={savedInsightsNext ? loadNextSavedInsights : undefined}
                            loadingMore={loadingMoreSavedInsights}
                            footer={(item) => <>Saved {dayjs(item.created_at).fromNow()}</>}
                            loading={savedInsightsLoading}
                            reportOnClick={() => {
                                reportInsightHistoryItemClicked(InsightHistoryType.SAVED, displayLocation)
                            }}
                        />
                    </TabPane>
                )}
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Dashboard Insights</span>}
                    key={InsightHistoryType.TEAM}
                    data-attr="insight-team-panel"
                >
                    <InsightPane
                        data={teamInsights}
                        loadMore={teamInsightsNext ? loadNextTeamInsights : undefined}
                        loadingMore={loadingMoreTeamInsights}
                        footer={(item) => (
                            <>
                                Saved {dayjs(item.created_at).fromNow()} by{' '}
                                {item.created_by?.first_name || item.created_by?.email || 'unknown'}
                            </>
                        )}
                        loading={teamInsightsLoading}
                        reportOnClick={() => {
                            reportInsightHistoryItemClicked(InsightHistoryType.TEAM, displayLocation)
                        }}
                    />
                </TabPane>
            </Tabs>
        </div>
    )
}
