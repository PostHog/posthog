import React, { useState } from 'react'
import { Tabs, Table, Modal, Input, Button } from 'antd'
import { toParams } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { PushpinOutlined, PushpinFilled, DeleteOutlined } from '@ant-design/icons'
import { useValues, useActions } from 'kea'
import { insightHistoryLogic, InsightHistory } from './insightHistoryLogic'
import { ViewType } from '../insightLogic'

const InsightHistoryType = {
    SAVED: 'SAVED',
    RECENT: 'RECENT',
}

const { TabPane } = Tabs

const determineFilters = (viewType: string, filters: Record<string, any>): JSX.Element => {
    const result = []
    if (viewType === ViewType.TRENDS) {
        let count = 0
        if (filters.events) count += filters.events.length
        if (filters.actions) count += filters.actions.length
        result.push([<b key="trend-entities">Entities:</b>, ` ${count}\n`])
        if (filters.interval) result.push([<b key="trend-interval">Interval:</b>, ` ${filters.interval}\n`])
        if (filters.shown_as) result.push([<b key="trend-shownas">Shown as:</b>, ` ${filters.shown_as}\n`])
        if (filters.breakdown) result.push([<b key="trend-breakdown">Breakdown:</b>, ` ${filters.breakdown}\n`])
        if (filters.compare) result.push([<b key="trend-compare">Compare:</b>, ` ${filters.compare}\n`])
        if (filters.properties)
            result.push([<b key="trend-properties">Properties:</b>, ` ${filters.properties.length}\n`])
    } else if (viewType === ViewType.SESSIONS) {
        if (filters.session) result.push([<b key="sessions-session">Session</b>, ` ${filters.session}\n`])
        if (filters.interval) result.push([<b key="sessions-interval">Interval:</b>, ` ${filters.interval}\n`])
        if (filters.compare) result.push([<b key="sessions-compare">Compare:</b>, ` ${filters.compare}\n`])
        if (filters.properties)
            result.push([<b key="sessions-properties">Properties:</b>, ` ${filters.properties.length}\n`])
    } else if (viewType === ViewType.RETENTION) {
        if (filters.target) result.push([<b key="retention-target">Target:</b>, ` ${filters.target.name}\n`])
        if (filters.properties)
            result.push([<b key="retention-properties">Properties:</b>, ` ${filters.properties.length}\n`])
    } else if (viewType === ViewType.PATHS) {
        if (filters.type) result.push([<b key="paths-type">Path Type:</b>, ` ${filters.type}\n`])
        if (filters.start) result.push([<b key="paths-start">Start Point:</b>, ` Specified\n`])
        if (filters.properties)
            result.push([<b key="paths-properties">Properties:</b>, ` ${filters.properties.length}\n`])
    } else if (viewType === ViewType.FUNNELS) {
        if (filters.name) result.push([<b key="funnel-name">Name:</b>, ` ${filters.name}\n`])
    }
    return <span>{result}</span>
}

export const InsightHistoryPanel: React.FC = () => {
    const { insights, insightsLoading, savedInsights, savedInsightsLoading } = useValues(insightHistoryLogic)
    const { saveInsight, deleteInsight } = useActions(insightHistoryLogic)

    const [visible, setVisible] = useState(false)
    const [activeTab, setActiveTab] = useState(InsightHistoryType.RECENT)
    const [selectedInsight, setSelectedInsight] = useState<number | null>(null)

    const savedColumns = [
        {
            title: 'Name',
            key: 'id',
            render: function RenderName(_: unknown, insight: InsightHistory) {
                return <Link to={'/insights?' + toParams(insight.filters)}>{insight.name}</Link>
            },
        },
        {
            title: 'Details',
            render: function RenderDetails(_: unknown, insight: InsightHistory) {
                return determineFilters(insight.type, insight.filters)
            },
        },
        {
            render: function RenderAction(_: unknown, insight: InsightHistory) {
                return (
                    <DeleteOutlined
                        onClick={() => {
                            deleteInsight(insight)
                        }}
                        style={{ cursor: 'pointer' }}
                    />
                )
            },
        },
    ]

    const recentColumns = [
        {
            title: 'Type',
            key: 'id',
            render: function RenderType(_: unknown, insight: InsightHistory) {
                return (
                    <Link to={'/insights?' + toParams(insight.filters)}>
                        {insight.type.charAt(0).toUpperCase() + insight.type.slice(1).toLowerCase()}
                    </Link>
                )
            },
        },
        {
            title: 'Details',
            render: function RenderDetails(_: unknown, insight: InsightHistory) {
                return determineFilters(insight.type, insight.filters)
            },
        },
        {
            render: function RenderAction(_: unknown, insight: InsightHistory) {
                return insight.saved ? (
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
                )
            },
        },
    ]

    return (
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
                <Table
                    style={{ whiteSpace: 'pre-line' }}
                    size="small"
                    columns={recentColumns}
                    loading={insightsLoading}
                    rowKey={(insight) => insight.id}
                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                    dataSource={insights}
                />
            </TabPane>
            <TabPane
                tab={<span data-attr="insight-saved-tab">Saved</span>}
                key={InsightHistoryType.SAVED}
                data-attr="insight-saved-pane"
            >
                <Table
                    style={{ whiteSpace: 'pre-line' }}
                    size="small"
                    columns={savedColumns}
                    loading={savedInsightsLoading}
                    rowKey={(insight) => insight.id}
                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                    dataSource={savedInsights}
                />
            </TabPane>
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
        </Tabs>
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

    return (
        <Modal
            visible={visible}
            footer={
                <Button type="primary" onClick={(): void => onSubmit(input)}>
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
