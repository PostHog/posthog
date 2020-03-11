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
        api.get('api/action/trends/?' + toParams(this.props.filters)).then(
            data => {
                data = data.sort((a, b) => b.count - a.count)
                this.setState({ data })
                this.props.onData && this.props.onData(data)
            }
        )
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
            data[0].labels ? (
                <table className="table">
                    <tbody>
                        <tr>
                            <th style={{ width: 100 }}>Action</th>
                            {filters.breakdown && <th>Breakdown</th>}
                            <th style={{ width: 50 }}>Count</th>
                        </tr>
                        {!filters.breakdown &&
                            data.map(item => (
                                <tr key={item.label}>
                                    <td>{item.label}</td>
                                    <td>{item.count}</td>
                                </tr>
                            ))}
                        {filters.breakdown &&
                            data
                                .filter(item => item.count > 0)
                                .map(item => [
                                    <tr key={item.label}>
                                        <td
                                            rowSpan={item.breakdown.length || 1}
                                        >
                                            {item.label}
                                        </td>
                                        <td className="text-overflow">
                                            {item.breakdown[0] &&
                                                item.breakdown[0].name}
                                        </td>
                                        <td>
                                            {item.breakdown[0] &&
                                                item.breakdown[0].count}
                                        </td>
                                    </tr>,
                                    item.breakdown.slice(1).map(i => (
                                        <tr key={i.name}>
                                            <td className="text-overflow">
                                                {i.name}
                                            </td>
                                            <td>{i.count}</td>
                                        </tr>
                                    )),
                                ])}
                    </tbody>
                </table>
            ) : (
                <p style={{ textAlign: 'center', marginTop: '4rem' }}>
                    We couldn't find any matching actions.
                </p>
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
