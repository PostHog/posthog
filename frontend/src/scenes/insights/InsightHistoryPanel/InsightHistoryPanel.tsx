import React, { useState } from 'react'
import { Tabs, Modal, Input, Button, List, Col, Spin } from 'antd'
import { toParams, dateFilterToText } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { PushpinOutlined, PushpinFilled, DeleteOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic } from './insightHistoryLogic'
import { ViewType } from '../insightLogic'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { formatPropertyLabel } from 'lib/utils'
import { cohortsModel } from '~/models'
import { PropertyFilter, Entity, CohortType } from '~/types'

const InsightHistoryType = {
    SAVED: 'SAVED',
    RECENT: 'RECENT',
}

const { TabPane } = Tabs

const determineFilters = (viewType: string, filters: Record<string, any>, cohorts: CohortType[]): JSX.Element => {
    const result = []
    if (viewType === ViewType.TRENDS) {
        let count = 0
        if (filters.events) count += filters.events.length
        if (filters.actions) count += filters.actions.length
        if (count > 0) {
            result.push([<b key="trend-entities">Entities:</b>, `\n`])
            if (filters.events) filters.events.forEach((event: Entity) => result.push(`- ${event.name}\n`))
            if (filters.actions) filters.actions.forEach((action: Entity) => result.push(`- ${action.name}\n`))
        }
        if (filters.interval) result.push([<b key="trend-interval">Interval:</b>, ` ${filters.interval}\n`])
        if (filters.shown_as) result.push([<b key="trend-shownas">Shown as:</b>, ` ${filters.shown_as}\n`])
        if (filters.breakdown) result.push([<b key="trend-breakdown">Breakdown:</b>, ` ${filters.breakdown}\n`])
        if (filters.compare) result.push([<b key="trend-compare">Compare:</b>, ` ${filters.compare}\n`])
    } else if (viewType === ViewType.SESSIONS) {
        if (filters.session) result.push([<b key="sessions-session">Session</b>, ` ${filters.session}\n`])
        if (filters.interval) result.push([<b key="sessions-interval">Interval:</b>, ` ${filters.interval}\n`])
        if (filters.compare) result.push([<b key="sessions-compare">Compare:</b>, ` ${filters.compare}\n`])
    } else if (viewType === ViewType.RETENTION) {
        if (filters.target) result.push([<b key="retention-target">Target:</b>, ` ${filters.target.name}\n`])
    } else if (viewType === ViewType.PATHS) {
        if (filters.type) result.push([<b key="paths-type">Path Type:</b>, ` ${filters.type}\n`])
        if (filters.start) result.push([<b key="paths-start">Start Point:</b>, ` Specified\n`])
    } else if (viewType === ViewType.FUNNELS) {
        if (filters.name) result.push([<b key="funnel-name">Name:</b>, ` ${filters.name}\n`])
    }
    if (filters.properties && filters.properties.length > 0) {
        result.push([<b key="insight-history-properties">Properties:</b>, `\n`])
        filters.properties.forEach((prop: PropertyFilter) =>
            result.push(`${formatPropertyLabel(prop, cohorts, keyMapping)}\n`)
        )
    }

    result.push([<b key="insight-history-date">Date: </b>, `${dateFilterToText(filters.date_from, filters.date_to)}\n`])
    return <span>{result}</span>
}

export const InsightHistoryPanel: React.FC = () => {
    const {
        insights,
        insightsLoading,
        savedInsights,
        savedInsightsLoading,
        insightsNext,
        savedInsightsNext,
        loadingMoreInsights,
        loadingMoreSavedInsights,
    } = useValues(insightHistoryLogic)
    const { saveInsight, deleteInsight, loadNextInsights, loadNextSavedInsights } = useActions(insightHistoryLogic)
    const { cohorts } = useValues(cohortsModel)

    const [visible, setVisible] = useState(false)
    const [activeTab, setActiveTab] = useState(InsightHistoryType.RECENT)
    const [selectedInsight, setSelectedInsight] = useState<number | null>(null)

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

    const loadMoreSavedInsights = savedInsightsNext ? (
        <div
            style={{
                textAlign: 'center',
                marginTop: 12,
                height: 32,
                lineHeight: '32px',
            }}
        >
            {loadingMoreSavedInsights ? <Spin /> : <Button onClick={loadNextSavedInsights}>Load more</Button>}
        </div>
    ) : null

    return (
        <div data-attr="insight-history-panel">
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
                        renderItem={(insight) => {
                            return (
                                <List.Item
                                    actions={[
                                        insight.saved ? (
                                            <PushpinFilled
                                                onClick={() => {
                                                    setVisible(true)
                                                    setSelectedInsight(insight.id)
                                                }}
                                                style={{ cursor: 'pointer' }}
                                            />
                                        ) : (
                                            <PushpinOutlined
                                                onClick={() => {
                                                    setVisible(true)
                                                    setSelectedInsight(insight.id)
                                                }}
                                                style={{ cursor: 'pointer' }}
                                            />
                                        ),
                                    ]}
                                >
                                    <Col style={{ whiteSpace: 'pre-line' }}>
                                        {insight.type && (
                                            <Link to={'/insights?' + toParams(insight.filters)}>
                                                {insight.type.charAt(0).toUpperCase() +
                                                    insight.type.slice(1).toLowerCase()}
                                            </Link>
                                        )}
                                        <br></br>
                                        <span>{determineFilters(insight.type, insight.filters, cohorts)}</span>
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
                    <List
                        loading={savedInsightsLoading}
                        dataSource={savedInsights}
                        loadMore={loadMoreSavedInsights}
                        renderItem={(insight) => {
                            return (
                                <List.Item
                                    key={insight.id}
                                    actions={[
                                        <DeleteOutlined
                                            key="insight-action-delete"
                                            onClick={() => {
                                                deleteInsight(insight)
                                            }}
                                            style={{ cursor: 'pointer' }}
                                        />,
                                    ]}
                                >
                                    <Col style={{ whiteSpace: 'pre-line' }}>
                                        {insight.type && (
                                            <Link to={'/insights?' + toParams(insight.filters)}>{insight.name}</Link>
                                        )}
                                        <br></br>
                                        <span>{determineFilters(insight.type, insight.filters, cohorts)}</span>
                                    </Col>
                                </List.Item>
                            )
                        }}
                    />
                </TabPane>
            </Tabs>
            <SaveChartModal
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

interface SaveChartModalProps {
    visible: boolean
    onCancel: () => void
    onSubmit: (input: string) => void
}

const SaveChartModal: React.FC<SaveChartModalProps> = (props) => {
    const { visible, onCancel, onSubmit } = props
    const [input, setInput] = useState<string>('')

    function _onCancel(): void {
        setInput('')
        onCancel()
    }

    function _onSubmit(input: string): void {
        setInput('')
        onSubmit(input)
    }

    return (
        <Modal
            visible={visible}
            footer={
                <Button type="primary" onClick={(): void => _onSubmit(input)}>
                    Save
                </Button>
            }
            onCancel={_onCancel}
        >
            <div data-attr="invite-team-modal">
                <h2>Save Chart</h2>
                <label>Name of Chart</label>
                <Input
                    name="Name"
                    required
                    type="text"
                    placeholder="DAUs Last 14 days"
                    value={input}
                    onChange={(e): void => setInput(e.target.value)}
                />
            </div>
        </Modal>
    )
}
