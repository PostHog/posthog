import React, { Component } from 'react'
import api from '../../lib/api'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'
import PropTypes from 'prop-types'

export class ActionsLineGraph extends Component {
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
        if (prevProps.filters !== this.props.filters) this.fetchGraph()
    }
    render() {
        let { data } = this.state
        return data ? (
            data[0] && data[0].labels ? (
                <LineGraph
                    datasets={data}
                    labels={data[0].labels}
                    onClick={({ dataset: { action }, day }) => {
                        console.log(action, day)
                        // api.get('api/action/trends/?' + toParams(this.props.filters))
                    }}
                />
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

ActionsLineGraph.propTypes = {
    filters: PropTypes.object.isRequired,
    onData: PropTypes.func,
}
