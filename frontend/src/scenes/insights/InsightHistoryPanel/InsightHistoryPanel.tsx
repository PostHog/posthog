import React, { useState } from 'react'
import { Tabs, Col, Row } from 'antd'
import { Loading } from 'lib/utils'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic } from './insightHistoryLogic'
import { DashboardItemType, InsightHistory } from '~/types'
import SaveModal from '../SaveModal'
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

function InsightPane({ data, loading }: { data: DashboardItemType[]; loading: boolean }): JSX.Element {
    const { loadTeamInsights, loadSavedInsights, loadInsights } = useActions(insightHistoryLogic)
    const { renameDashboardItem, duplicateDashboardItem } = useActions(dashboardItemsModel)

    return (
        <Row gutter={[16, 16]}>
            {loading && <Loading />}
            {data &&
                data.map((insight: DashboardItemType) => (
                    <Col xs={8} key={insight.id} style={{ height: 270 }}>
                        <DashboardItem
                            item={{ ...insight, color: undefined }}
                            options={<div className="dashboard-item-settings">hi</div>}
                            key={insight.id + '_user'}
                            loadDashboardItems={() => {
                                loadInsights()
                                loadSavedInsights()
                                loadTeamInsights()
                            }}
                            renameDashboardItem={renameDashboardItem}
                            moveDashboardItem={(item: DashboardItemType, dashboardId: number) =>
                                duplicateDashboardItem(item, dashboardId)
                            }
                            preventLoading={true}
                            footer={
                                <div className="dashboard-item-footer">
                                    Last saved {moment(insight.created_at).fromNow()}
                                </div>
                            }
                        />
                    </Col>
                ))}
        </Row>
    )
}

export const InsightHistoryPanel: React.FC<InsightHistoryPanelProps> = () => {
    const {
        insights,
        insightsLoading,
        savedInsights,
        savedInsightsLoading,
        teamInsights,
        teamInsightsLoading,
    } = useValues(insightHistoryLogic)
    const { saveInsight } = useActions(insightHistoryLogic)

    const [visible, setVisible] = useState(false)
    const [activeTab, setActiveTab] = useState(InsightHistoryType.SAVED)
    const [selectedInsight, setSelectedInsight] = useState<InsightHistory | null>(null)

    // const loadMoreInsights = insightsNext ? (
    //     <div
    //         style={{
    //             textAlign: 'center',
    //             marginTop: 12,
    //             height: 32,
    //             lineHeight: '32px',
    //         }}
    //     >
    //         {loadingMoreInsights ? <Spin /> : <Button onClick={loadNextInsights}>Load more</Button>}
    //     </div>
    // ) : null

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

    // const loadMoreTeamInsights = teamInsightsNext ? (
    //     <div
    //         style={{
    //             textAlign: 'center',
    //             marginTop: 12,
    //             height: 32,
    //             lineHeight: '32px',
    //         }}
    //     >
    //         {loadingMoreTeamInsights ? <Spin /> : <Button onClick={loadNextTeamInsights}>Load more</Button>}
    //     </div>
    // ) : null

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
                    <InsightPane data={insights} loading={insightsLoading} />
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Saved</span>}
                    key={InsightHistoryType.SAVED}
                    data-attr="insight-saved-pane"
                >
                    <InsightPane data={savedInsights} loading={savedInsightsLoading} />
                </TabPane>
                <TabPane
                    tab={<span data-attr="insight-saved-tab">Team</span>}
                    key={InsightHistoryType.TEAM}
                    data-attr="insight-team-panel"
                >
                    <InsightPane data={teamInsights} loading={teamInsightsLoading} />
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
