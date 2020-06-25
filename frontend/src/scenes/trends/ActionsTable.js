import React, { useEffect } from 'react'
import { Loading, toParams } from '../../lib/utils'
import { Table } from 'antd'
import PropTypes from 'prop-types'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export function ActionsTable({ dashboardItemId = null, filters: filtersParam }) {
    const { filters, results, resultsLoading } = useValues(trendsLogic({ dashboardItemId, filters: filtersParam }))
    const { loadResults } = useActions(trendsLogic({ dashboardItemId, filters: filtersParam }))

    useEffect(() => {
        loadResults()
    }, [toParams(filters)])

    let data = results
    if (!filters.session) data = data.sort((a, b) => b.count - a.count)
    return data && !resultsLoading ? (
        data[0] && (filters.session || data[0].labels) ? (
            <Table
                size="small"
                columns={[
                    {
                        title: filters.session ? 'Session Attribute' : 'Action',
                        dataIndex: 'label',
                        render: function renderLabel(_, { label }) {
                            return <div style={{ wordBreak: 'break-all' }}>{label}</div>
                        },
                    },
                    { title: filters.session ? 'Value' : 'Count', dataIndex: 'count' },
                ]}
                rowKey={item => item.label}
                pagination={{ pageSize: 9999, hideOnSinglePage: true }}
                dataSource={data}
                data-attr="trend-table-graph"
            />
        ) : (
            <p style={{ textAlign: 'center', marginTop: '4rem' }}>We couldn't find any matching actions.</p>
        )
    ) : (
        <Loading />
    )
}

ActionsTable.propTypes = {
    filters: PropTypes.object.isRequired,
}
