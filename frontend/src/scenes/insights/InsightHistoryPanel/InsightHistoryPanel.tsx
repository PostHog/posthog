import React, { useState } from 'react'
import { Tabs, Modal, Input, Button, List, Col, Spin, Table, Row, Tooltip } from 'antd'
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

const columns = [
    {
        render: function renderKey(item) {
            return <b style={{ marginLeft: -8 }}>{item.key}</b>
        },
    },
    {
        render: function renderValue(item) {
            return <span>{item.value}</span>
        },
    },
]

const determineFilters = (viewType: string, filters: Record<string, any>, cohorts: CohortType[]): JSX.Element => {
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
        if (filters.interval) result.push({ key: 'Interval', value: `${filters.interval}\n` })
        if (filters.shown_as) result.push({ key: 'Shown As', value: `${filters.shown_as}\n` })
        if (filters.breakdown) result.push({ key: 'Breakdown', value: `${filters.breakdown}\n` })
        if (filters.compare) result.push({ key: 'Compare', value: `${filters.compare}\n` })
    } else if (viewType === ViewType.SESSIONS) {
        if (filters.session) result.push({ key: 'Session', value: `${filters.session}\n` })
        if (filters.interval) result.push({ key: 'Interval', value: `${filters.interval}\n` })
        if (filters.compare) result.push({ key: 'Compare', value: `${filters.compare}\n` })
    } else if (viewType === ViewType.RETENTION) {
        if (filters.target) result.push({ key: 'Target', value: `${filters.target.name}\n` })
    } else if (viewType === ViewType.PATHS) {
        if (filters.type) result.push({ key: 'Path Type', value: `${filters.type}\n` })
        if (filters.start) result.push({ key: 'Start Point', value: `Specified\n` })
    } else if (viewType === ViewType.FUNNELS) {
        if (filters.name) result.push({ key: 'Name', value: `${filters.name}\n` })
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
                                                            setSelectedInsight(insight.id)
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
                        renderItem={(insight) => {
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
