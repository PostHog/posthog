import React, { useState } from 'react'
import { Tabs, Button, List, Col, Spin, Table, Row, Tooltip } from 'antd'
import { toParams, dateFilterToText } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { PushpinOutlined, PushpinFilled, DeleteOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic } from './insightHistoryLogic'
import { ViewType } from '../insightLogic'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { formatPropertyLabel } from 'lib/utils'
import { cohortsModel } from '~/models'
import { PropertyFilter, Entity, CohortType, InsightHistory } from '~/types'
import SaveModal from '../SaveModal'

const InsightHistoryType = {
    SAVED: 'SAVED',
    RECENT: 'RECENT',
    TEAM: 'TEAM',
}

const { TabPane } = Tabs

const columns = [
    {
        render: function renderKey(item) {
            return <b style={{ marginLeft: -8 }}>{item.key}</b>
        },
        width: 110,
    },
    {
        render: function renderValue(item) {
            return <span>{item.value}</span>
        },
    },
]

export const determineFilters = (
    viewType: string,
    filters: Record<string, any>,
    cohorts: CohortType[]
): JSX.Element => {
    const result = []
    if (viewType === ViewType.TRENDS) {
        let count = 0
        if (filters.events) count += filters.events.length
        if (filters.actions) count += filters.actions.length
        if (count > 0) {
            const entity: string[] = []
            if (filters.events) filters.events.forEach((event: Entity) => entity.push(`- ${event.name}\n`))
            if (filters.actions) filters.actions.forEach((action: Entity) => entity.push(`- ${action.name}\n`))
            result.push({ key: 'Entities', value: entity })
        }
        if (filters.interval) result.push({ key: 'Interval', value: `${filters.interval}` })
        if (filters.shown_as) result.push({ key: 'Shown As', value: `${filters.shown_as}` })
        if (filters.breakdown) result.push({ key: 'Breakdown', value: `${filters.breakdown}` })
        if (filters.compare) result.push({ key: 'Compare', value: `${filters.compare}` })
    } else if (viewType === ViewType.SESSIONS) {
        if (filters.session) result.push({ key: 'Session', value: `${filters.session}` })
        if (filters.interval) result.push({ key: 'Interval', value: `${filters.interval}` })
        if (filters.compare) result.push({ key: 'Compare', value: `${filters.compare}` })
    } else if (viewType === ViewType.RETENTION) {
        if (filters.target) result.push({ key: 'Target', value: `${filters.target.name}` })
    } else if (viewType === ViewType.PATHS) {
        if (filters.type) result.push({ key: 'Path Type', value: `${filters.type || filters.path_type}` })
        if (filters.start) result.push({ key: 'Start Point', value: `Specified` })
    } else if (viewType === ViewType.FUNNELS) {
        let count = 0
        if (filters.events) count += filters.events.length
        if (filters.actions) count += filters.actions.length
        if (count > 0) {
            const entity: string[] = []
            if (filters.events) filters.events.forEach((event: Entity) => entity.push(`- ${event.name || event.id}\n`))
            if (filters.actions)
                filters.actions.forEach((action: Entity) =>
                    entity.push(`- ${action.name || '(action: ' + action.id + ')'}\n`)
                )
            result.push({ key: 'Entities', value: entity })
        }
    }
    if (filters.properties && filters.properties.length > 0) {
        const properties: string[] = []
        filters.properties.forEach((prop: PropertyFilter) =>
            properties.push(`${formatPropertyLabel(prop, cohorts, keyMapping)}\n`)
        )
        result.push({ key: 'Properties', value: properties })
    }
    if (filters.date_from || filters.date_to)
        result.push({ key: 'Date Range', value: `${dateFilterToText(filters.date_from, filters.date_to)}\n` })
    return (
        <Table
            showHeader={false}
            size={'small'}
            dataSource={result}
            columns={columns}
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
        />
    )
}

interface InsightHistoryPanelProps {
    onChange: () => void
}

export const InsightHistoryPanel: React.FC<InsightHistoryPanelProps> = ({ onChange }: InsightHistoryPanelProps) => {
    const {
        insights,
        insightsLoading,
        savedInsights,
        savedInsightsLoading,
        teamInsights,
        teamInsightsLoading,
        insightsNext,
        savedInsightsNext,
        teamInsightsNext,
        loadingMoreInsights,
        loadingMoreSavedInsights,
        loadingMoreTeamInsights,
    } = useValues(insightHistoryLogic)
    const { saveInsight, deleteInsight, loadNextInsights, loadNextSavedInsights, loadNextTeamInsights } = useActions(
        insightHistoryLogic
    )
    const { cohorts } = useValues(cohortsModel)

    const [visible, setVisible] = useState(false)
    const [activeTab, setActiveTab] = useState(InsightHistoryType.RECENT)
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
                        renderItem={(insight: InsightHistory) => {
                            return (
                                <List.Item>
                                    <Col style={{ whiteSpace: 'pre-line', width: '100%' }}>
                                        <Row justify="space-between" align="middle">
                                            {insight.type && (
                                                <Link onClick={onChange} to={'/insights?' + toParams(insight.filters)}>
                                                    {insight.type.charAt(0).toUpperCase() +
                                                        insight.type.slice(1).toLowerCase()}
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
                        renderItem={(insight: InsightHistory) => {
                            return (
                                <List.Item key={insight.id}>
                                    <Col style={{ whiteSpace: 'pre-line', width: '100%' }}>
                                        <Row justify="space-between" align="middle">
                                            {insight.type && (
                                                <Link onClick={onChange} to={'/insights?' + toParams(insight.filters)}>
                                                    {insight.name}
                                                </Link>
                                            )}
                                            <DeleteOutlined
                                                className="clickable button-border"
                                                key="insight-action-delete"
                                                onClick={() => {
                                                    deleteInsight(insight)
                                                }}
                                                style={{ cursor: 'pointer' }}
                                            />
                                        </Row>
                                        <span>{determineFilters(insight.type, insight.filters, cohorts)}</span>
                                    </Col>
                                </List.Item>
                            )
                        }}
                    />
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
                                            {insight.type && (
                                                <Link onClick={onChange} to={'/insights?' + toParams(insight.filters)}>
                                                    {insight.name}
                                                </Link>
                                            )}
                                        </Row>
                                        <span>{determineFilters(insight.type, insight.filters, cohorts)}</span>
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
