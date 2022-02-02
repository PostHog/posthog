import React from 'react'
import { Col, Divider, Row, Statistic } from 'antd'
import { useValues } from 'kea'
import { deadLetterQueueLogic } from './deadLetterQueueLogic'
import { userLogic } from 'scenes/userLogic'
import { LemonTable } from 'lib/components/LemonTable'
import './DeadLetterQueue.scss'

export function MetricsTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const { singleValueMetrics, tableMetrics, deadLetterQueueMetricsLoading } = useValues(deadLetterQueueLogic)

    if (!user?.is_staff) {
        return <></>
    }

    return (
        <div>
            <br />

            <Row gutter={32}>
                {singleValueMetrics.map((row) => (
                    <Col key={row.key}>
                        <Statistic title={row.metric} value={(row.value || '0').toLocaleString('en-US')} />
                    </Col>
                ))}
            </Row>

            <Divider />

            {tableMetrics.map((row) => (
                <div key={row.key}>
                    <h2>{row.metric}</h2>
                    <LemonTable
                        columns={[
                            {
                                title: row.subrows?.columns[0],
                                dataIndex: 'key',
                            },
                            {
                                title: row.subrows?.columns[1],
                                dataIndex: 'value',
                            },
                        ]}
                        dataSource={row.subrows?.rows.map(([key, value]) => ({ key, value })) || []}
                        loading={deadLetterQueueMetricsLoading}
                        embedded
                    />

                    <Divider />
                </div>
            ))}
        </div>
    )
}
