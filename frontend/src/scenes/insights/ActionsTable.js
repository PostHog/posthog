import React from 'react'
import { Loading, formatLabel } from '../../lib/utils'
import { Table } from 'antd'
import PropTypes from 'prop-types'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/insights/trendsLogic'

export function ActionsTable({ dashboardItemId = null, view, filters: filtersParam, cachedResults }) {
    const logic = trendsLogic({ dashboardItemId, view, filters: filtersParam, cachedResults })
    const { filters, results, resultsLoading } = useValues(logic)

    let data = results
    if (!filters.session) {
        data = data.sort((a, b) => b.aggregated_value - a.aggregated_value)
    }
    return data && !resultsLoading ? (
        data[0] && (filters.session || data[0].labels) ? (
            <Table
                size="small"
                columns={[
                    {
                        title: filters.session ? 'Session Attribute' : 'Action',
                        dataIndex: 'label',
                        render: function renderLabel(_, { label, action }) {
                            return (
                                <div style={{ wordBreak: 'break-all' }}>
                                    {filters.session ? label : formatLabel(label, action)}
                                </div>
                            )
                        },
                    },
                    {
                        title: filters.session ? 'Value' : 'Count',
                        dataIndex: filters.session ? 'count' : 'aggregated_value',
                    },
                ]}
                rowKey="label"
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
