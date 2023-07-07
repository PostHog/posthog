import { useMemo, useState } from 'react'
import { Button, Checkbox, Table } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { QuerySummary } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

export function InternalMetricsTab(): JSX.Element {
    const { openSections, queries, queriesLoading } = useValues(systemStatusLogic)
    const { setOpenSections, loadQueries } = useActions(systemStatusLogic)

    const [showIdle, setShowIdle] = useState(false)
    const postgresQueries = useMemo(
        () => queries?.postgres_running?.filter(({ state }) => showIdle || state !== 'idle'),
        [showIdle, queries]
    )

    const reloadQueries = (e: React.MouseEvent): void => {
        e.stopPropagation()
        loadQueries()
    }

    return (
        <>
            <LemonCollapse
                activeKeys={openSections}
                onChange={(keys) => setOpenSections(keys)}
                multiple
                panels={[
                    {
                        key: '1',
                        header: 'PostgreSQL - currently running queries',
                        content: (
                            <>
                                <div className="mb-4 float-right">
                                    <Checkbox
                                        checked={showIdle}
                                        onChange={(e) => {
                                            setShowIdle(e.target.checked)
                                        }}
                                    >
                                        Show idle queries
                                    </Checkbox>
                                    <Button style={{ marginLeft: 8 }} onClick={reloadQueries}>
                                        <ReloadOutlined /> Reload Queries
                                    </Button>
                                </div>
                                <QueryTable queries={postgresQueries} loading={queriesLoading} />
                            </>
                        ),
                    },
                    queries?.clickhouse_running != undefined && {
                        key: '2',
                        header: 'Clickhouse - currently running queries',
                        content: (
                            <>
                                <div className="mb-4 float-right">
                                    <Button style={{ marginLeft: 8 }} onClick={reloadQueries}>
                                        <ReloadOutlined /> Reload Queries
                                    </Button>
                                </div>
                                <QueryTable queries={queries?.clickhouse_running} loading={queriesLoading} />
                            </>
                        ),
                    },
                    queries?.clickhouse_slow_log != undefined && {
                        key: '3',
                        header: 'Clickhouse - slow query log (past 6 hours)',
                        content: (
                            <>
                                <div className="mb-4 float-right">
                                    <Button style={{ marginLeft: 8 }} onClick={reloadQueries}>
                                        <ReloadOutlined /> Reload Queries
                                    </Button>
                                </div>
                                <QueryTable queries={queries?.clickhouse_slow_log} loading={queriesLoading} />
                            </>
                        ),
                    },
                ]}
            />
        </>
    )
}

function QueryTable(props: {
    queries?: QuerySummary[]
    loading: boolean
    columnExtra?: Record<string, any>
}): JSX.Element {
    const columns: ColumnsType<QuerySummary> = [
        {
            title: 'duration',
            dataIndex: 'duration',
            key: 'duration',
            sorter: (a, b) => +a.duration - +b.duration,
        },
        {
            title: 'query',
            dataIndex: 'query',
            render: function RenderAnalyze({}, item: QuerySummary) {
                return item.query
            },
            key: 'query',
        },
    ]

    if (props.queries && props.queries.length > 0) {
        Object.keys(props.queries[0]).forEach((column) => {
            if (column !== 'duration' && column !== 'query') {
                columns.push({ title: column, dataIndex: column, key: column })
            }
        })
    }

    return (
        <Table
            dataSource={props.queries || []}
            columns={columns}
            loading={props.loading}
            pagination={{ pageSize: 30, hideOnSinglePage: true }}
            size="small"
            bordered
            style={{ overflowX: 'auto', overflowY: 'auto' }}
            locale={{ emptyText: 'No queries found' }}
        />
    )
}
