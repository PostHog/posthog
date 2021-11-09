import React from 'react'
import { Loading, formatLabel, maybeAddCommasToInteger } from 'lib/utils'
import { Table } from 'antd'
import PropTypes from 'prop-types'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { ActionFilter, TrendResultWithAggregate } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

export function ActionsTable(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { filters, indexedResults, resultsLoading } = useValues(logic)

    let data = indexedResults as any as TrendResultWithAggregate[]
    if (!filters.session && data) {
        data = [...data].sort((a, b) => b.aggregated_value - a.aggregated_value)
    }

    data = data.map((d: any) => {
        const key: string = filters.session ? 'count' : 'aggregated_value'
        const value: any = d[key]
        d[key + '_formatted'] = maybeAddCommasToInteger(value)
        return d
    })

    return data && !resultsLoading ? (
        data[0] && (filters.session || data[0].labels) ? (
            <Table
                size="small"
                columns={[
                    {
                        title: filters.session ? 'Session Attribute' : 'Action',
                        dataIndex: 'label',
                        render: function renderLabel(_, { label, action }: { label: string; action: ActionFilter }) {
                            return (
                                <div style={{ wordBreak: 'break-all' }}>
                                    {filters.session ? label : filters.formula ? label : formatLabel(label, action)}
                                </div>
                            )
                        },
                    },
                    {
                        title: filters.session ? 'Value' : 'Count',
                        dataIndex: filters.session ? 'count_formatted' : 'aggregated_value_formatted',
                    },
                ]}
                rowKey="label"
                pagination={{ pageSize: 9999, hideOnSinglePage: true }}
                dataSource={data}
                data-attr="actions-table-graph"
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
