import React, { Component } from 'react'
import api from '../../lib/api'
import { Loading, toParams } from '../../lib/utils'
import { LineGraph } from './LineGraph'

let colors = [
    'blue',
    'yellow',
    'green',
    'red',
    'purple',
    'gray',
    'indigo',
    'pink',
    'orange',
    'teal',
    'cyan',
    'gray-dark',
]
let getColorVar = variable =>
    getComputedStyle(document.body).getPropertyValue('--' + variable)
export class ActionsPie extends Component {
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
                let color_list = colors.map(color => getColorVar(color))
                this.setState({
                    data: [
                        {
                            labels: data.map(item => item.label),
                            data: data.map(
                                item =>
                                    item.data &&
                                    item.data.reduce((prev, d) => prev + d, 0)
                            ),
                            backgroundColor: color_list,
                            hoverBackgroundColor: color_list,
                            hoverBorderColor: color_list,
                            borderColor: color_list,
                            hoverBorderWidth: 10,
                            borderWidth: 1,
                        },
                    ],
                    total: data.reduce((prev, item) => prev + item.count, 0),
                })
                this.props.onData && this.props.onData(data)
            }
        )
    }
    componentDidUpdate(prevProps) {
        if (prevProps.filters !== this.props.filters) this.fetchGraph()
    }
    render() {
        let { data, total } = this.state
        return data ? (
            data[0] && data[0].labels ? (
                <div
                    style={{
                        position: 'absolute',
                        width: '100%',
                        height: '100%',
                    }}
                >
                    <h1
                        style={{
                            position: 'absolute',
                            margin: '0 auto',
                            left: '50%',
                            top: '50%',
                            fontSize: '3rem',
                        }}
                    >
                        <div style={{ marginLeft: '-50%', marginTop: -30 }}>
                            {total}
                        </div>
                    </h1>
                    <LineGraph
                        type="doughnut"
                        datasets={data}
                        labels={data[0].labels}
                    />
                </div>
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
