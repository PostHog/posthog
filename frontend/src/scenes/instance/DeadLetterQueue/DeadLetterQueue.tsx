import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Tabs } from 'antd'
import { useValues, useActions } from 'kea'
import { deadLetterQueueLogic } from './deadLetterQueueLogic'
import { userLogic } from 'scenes/userLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'

export const scene: SceneExport = {
    component: DeadLetterQueue,
    logic: deadLetterQueueLogic,
}

interface DataRow {
    key: string
    value: number | string
}

const { TabPane } = Tabs

export function DeadLetterQueue(): JSX.Element {
    const { user } = useValues(userLogic)
    const { deadLetterQueueMetrics, activeTab, currentMetric, deadLetterQueueMetricsLoading } =
        useValues(deadLetterQueueLogic)
    const { setActiveTab } = useActions(deadLetterQueueLogic)

    const tableData: DataRow[] = []

    for (const [key, value] of currentMetric.subrows?.rows || []) {
        tableData.push({ key, value })
    }

    console.log(tableData)

    const columns: LemonTableColumns<DataRow> = [
        {
            title: currentMetric.subrows?.columns[0],
            dataIndex: 'key',
        },
        {
            title: currentMetric.subrows?.columns[1],
            dataIndex: 'value',
        },
    ]

    return (
        <div>
            {user?.is_staff ? (
                <>
                    <PageHeader
                        title="Dead Letter Queue"
                        caption={
                            <>
                                <p>Manage your instance's dead letter queue.</p>
                            </>
                        }
                    />

                    <Tabs activeKey={activeTab} onChange={(t) => setActiveTab(t)}>
                        {deadLetterQueueMetrics.map((row) => (
                            <TabPane tab={row.metric} key={row.key} />
                        ))}
                    </Tabs>

                    {currentMetric ? (
                        <>
                            {currentMetric.value ? (
                                <h2>{currentMetric.value}</h2>
                            ) : (
                                <LemonTable
                                    columns={columns}
                                    dataSource={tableData}
                                    loading={deadLetterQueueMetricsLoading}
                                    embedded
                                />
                            )}
                        </>
                    ) : null}
                </>
            ) : null}
        </div>
    )
}
