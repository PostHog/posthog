import React from 'react'
import { Divider, Tag } from 'antd'
import { useValues } from 'kea'
import { deadLetterQueueLogic } from './deadLetterQueueLogic'
import { userLogic } from 'scenes/userLogic'
import { LemonTable } from 'lib/components/LemonTable'
import './DeadLetterQueue.scss'

export function MetricsTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const { deadLetterQueueMetrics, deadLetterQueueMetricsLoading } = useValues(deadLetterQueueLogic)

    if (!user?.is_staff) {
        return <></>
    }

    return (
        <div>
            <br />
            {deadLetterQueueMetrics.map((row) => (
                <>
                    {row.subrows ? (
                        <>
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
                        </>
                    ) : (
                        <h2>
                            {`${row.metric}:`} <Tag color="blue">{row.value || '0'}</Tag>
                        </h2>
                    )}

                    <Divider />
                </>
            ))}
        </div>
    )
}
