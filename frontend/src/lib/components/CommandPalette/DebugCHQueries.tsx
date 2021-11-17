import React from 'react'
import { Modal, Table } from 'antd'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

export async function debugCHQueries(): Promise<void> {
    const results = await api.get('api/debug_ch_queries/')

    Modal.info({
        visible: true,
        width: '80%',
        title: 'ClickHouse queries recently executed for this user',
        icon: null,
        content: (
            <>
                <Table
                    columns={[
                        { title: 'Timestamp', render: (item) => dayjs(item.timestamp).fromNow() },
                        {
                            title: 'Query',
                            render: function query(item) {
                                return (
                                    <pre className="code" style={{ maxWidth: 600, fontSize: 12 }}>
                                        {item.query}
                                    </pre>
                                )
                            },
                        },
                        {
                            title: 'Execution duration (seconds)',
                            render: function exec(item) {
                                return <>{Math.round((item.execution_time + Number.EPSILON) * 100) / 100}</>
                            },
                        },
                    ]}
                    dataSource={results}
                    size="small"
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                />
            </>
        ),
    })
}
