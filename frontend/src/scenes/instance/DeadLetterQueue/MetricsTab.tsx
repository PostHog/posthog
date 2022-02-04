import React from 'react'
import { Col, Divider, Row, Statistic } from 'antd'
import { useValues, useActions } from 'kea'
import { deadLetterQueueLogic } from './deadLetterQueueLogic'
import { userLogic } from 'scenes/userLogic'
import { LemonTable } from 'lib/components/LemonTable'
import { LemonButton } from 'lib/components/LemonButton'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { IconRefresh } from 'lib/components/icons'

export function MetricsTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const { singleValueMetrics, tableMetrics, deadLetterQueueMetricsLoading } = useValues(deadLetterQueueLogic)
    const { loadDeadLetterQueueMetrics } = useActions(deadLetterQueueLogic)

    if (!user?.is_staff) {
        return <></>
    }

    return (
        <div>
            <br />

            <div className="mb float-right">
                <LemonButton
                    icon={deadLetterQueueMetricsLoading ? <Spinner size="sm" /> : <IconRefresh />}
                    onClick={loadDeadLetterQueueMetrics}
                    type="secondary"
                    compact
                >
                    Refresh
                </LemonButton>
            </div>

            <Row gutter={32}>
                {singleValueMetrics.map((row) => (
                    <Col key={row.key}>
                        <Statistic
                            title={row.metric}
                            value={(row.value || '0').toLocaleString('en-US')}
                            loading={deadLetterQueueMetricsLoading}
                        />
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
                        defaultSorting={{
                            columnKey: 'value',
                            order: -1,
                        }}
                        embedded
                    />

                    <Divider />
                </div>
            ))}
        </div>
    )
}
