import React, { Component } from 'react'
import api from '../../lib/api'
import { Loading, toParams } from '../../lib/utils'
import { Table } from 'antd'
import PropTypes from 'prop-types'

export class ActionsTable extends Component {
    constructor(props) {
        super(props)

        this.state = {}
        this.fetchGraph = this.fetchGraph.bind(this)
        this.fetchGraph()
    }
    fetchGraph() {
        let url = 'api/action/trends/?'
        if (this.props.filters.session) url = 'api/event/sessions/?'
        api.get(url + toParams(this.props.filters)).then(data => {
            if (this.props.filters.session) data = data.result
            else data.sort((a, b) => b.count - a.count)
            this.setState({ data })
            this.props.onData && this.props.onData(data)
        })
    }
    componentDidUpdate(prevProps) {
        if (prevProps.filters !== this.props.filters) {
            this.fetchGraph()
        }
    }
    render() {
        let { data } = this.state
        let { filters } = this.props
        return data ? (
            data[0] && (filters.session || data[0].labels) ? (
                <Table
                    size="small"
                    columns={[
                        {
                            title: filters.session ? 'Session Attribute' : 'Action',
                            dataIndex: 'label',
                            render: (_, { label }) => <div style={{ wordBreak: 'break-all' }}>{label}</div>,
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
}
ActionsTable.propTypes = {
    filters: PropTypes.object.isRequired,
    onData: PropTypes.func,
}
