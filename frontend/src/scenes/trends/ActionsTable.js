import React, { Component } from 'react'
import api from '../../lib/api'
import { Loading, toParams } from '../../lib/utils'
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
            if (!this.props.filters.session) data = data.sort((a, b) => b.count - a.count)
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
                <table className="table" dataattr="trend-table-graph">
                    <tbody>
                        <tr>
                            <th style={{ width: 100 }}>{filters.session ? 'Session Attribute' : 'Action'}</th>
                            <th style={{ width: 50 }}>{filters.session ? 'Value' : 'Count'}</th>
                        </tr>

                        {data.map(item => (
                            <tr key={item.label}>
                                <td>{item.label}</td>
                                <td>{item.count}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
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
