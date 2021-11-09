import React, { useMemo, useState } from 'react'
import { Button, Card, Checkbox, Collapse, Table } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { QuerySummary } from '~/types'
import { ColumnsType } from 'antd/lib/table'
import { AnalyzeQueryModal } from 'scenes/instance/SystemStatus/AnalyzeQueryModal'
import { Link } from 'lib/components/Link'

export function InternalMetricsTab(): JSX.Element {
    const { openSections, systemStatus, queries, queriesLoading, showAnalyzeQueryButton } = useValues(systemStatusLogic)
    const { setOpenSections, loadQueries } = useActions(systemStatusLogic)

    const [showIdle, setShowIdle] = useState(false)
    const postgresQueries = useMemo(
        () => queries?.postgres_running?.filter(({ state }) => showIdle || state !== 'idle'),
        [showIdle, queries]
    )

    const dashboard = systemStatus?.internal_metrics.clickhouse

    const reloadQueries = (e: React.MouseEvent): void => {
        e.stopPropagation()
        loadQueries()
    }

    return (
        <Card>
            <Collapse activeKey={openSections} onChange={(keys) => setOpenSections(keys as string[])}>
                {dashboard ? (
                    <Collapse.Panel header="Dashboards" key="0">
                        <Dashboard id={dashboard.id.toString()} shareToken={dashboard.share_token} internal />
                    </Collapse.Panel>
                ) : null}
                <Collapse.Panel header="PostgreSQL - currently running queries" key="1">
                    <div className="mb float-right">
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
                </Collapse.Panel>
                {queries?.clickhouse_running != undefined ? (
                    <Collapse.Panel header="Clickhouse - currently running queries" key="2">
                        <div className="mb float-right">
                            <Button style={{ marginLeft: 8 }} onClick={reloadQueries}>
                                <ReloadOutlined /> Reload Queries
                            </Button>
                        </div>
                        <QueryTable
                            queries={queries?.clickhouse_running}
                            loading={queriesLoading}
                            showAnalyze={showAnalyzeQueryButton}
                        />
                    </Collapse.Panel>
                ) : null}
                {queries?.clickhouse_slow_log != undefined ? (
                    <Collapse.Panel header="Clickhouse - slow query log (past 6 hours)" key="3">
                        <div className="mb float-right">
                            <Button style={{ marginLeft: 8 }} onClick={reloadQueries}>
                                <ReloadOutlined /> Reload Queries
                            </Button>
                        </div>
                        <QueryTable
                            queries={queries?.clickhouse_slow_log}
                            loading={queriesLoading}
                            showAnalyze={showAnalyzeQueryButton}
                        />
                    </Collapse.Panel>
                ) : null}
            </Collapse>

            <AnalyzeQueryModal />
        </Card>
    )
}

function QueryTable(props: {
    showAnalyze?: boolean
    queries?: QuerySummary[]
    loading: boolean
    columnExtra?: Record<string, any>
}): JSX.Element {
    const { openAnalyzeModalWithQuery } = useActions(systemStatusLogic)
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
                if (!props.showAnalyze) {
                    return item.query
                }
                return (
                    <Link to="#" onClick={() => openAnalyzeModalWithQuery(item.query)}>
                        {item.query}
                    </Link>
                )
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
