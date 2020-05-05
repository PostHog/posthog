import React, { Component } from 'react'
import api from 'lib/api'
import FunnelGraph from 'funnel-graph-js'
import { Link } from 'lib/components/Link'
import { Loading } from 'lib/utils'
import PropTypes from 'prop-types'

export class FunnelViz extends Component {
    container = React.createRef()
    graphContainer = React.createRef()
    constructor(props) {
        super(props)

        this.state = {
            funnel: props.funnel,
        }
        this.buildChart = this.buildChart.bind(this)
        if (!props.funnel) this.fetchFunnel.call(this)
    }
    componentDidMount() {
        if (this.props.funnel) this.buildChart()
        window.addEventListener('resize', this.buildChart)
    }
    componentWillUnmount() {
        window.removeEventListener('resize', this.buildChart)
    }
    fetchFunnel() {
        api.get('api/funnel/' + this.props.filters.funnel_id).then(funnel => this.setState({ funnel }, this.buildChart))
    }
    componentDidUpdate(prevProps) {
        if (prevProps.funnel !== this.props.funnel && this.state.funnel) {
            this.setState({ funnel: this.props.funnel }, this.buildChart)
        }
    }
    buildChart() {
        if (!this.state.funnel || this.state.funnel.steps.length == 0) return
        if (this.container.current) this.container.current.innerHTML = ''
        let graph = new FunnelGraph({
            container: '.funnel-graph',
            data: {
                labels: this.state.funnel.steps.map(step => `${step.name} (${step.count})`),
                values: this.state.funnel.steps.map(step => step.count),
                colors: ['#66b0ff', 'var(--blue)'],
            },
            displayPercent: true,
        })
        graph.createContainer = () => {}
        graph.container = this.container.current
        graph.graphContainer = document.createElement('div')
        graph.graphContainer.classList.add('svg-funnel-js__container')
        graph.container.appendChild(graph.graphContainer)

        graph.draw()
    }
    render() {
        let { funnel } = this.state
        return funnel ? (
            funnel.steps.length > 0 ? (
                <div ref={this.container} className="svg-funnel-js" style={{ height: '100%', width: '100%' }}></div>
            ) : (
                <p style={{ margin: '1rem' }}>
                    This funnel doesn't have any steps.{' '}
                    <Link to={'/funnel/' + funnel.id}>Click here to add some steps.</Link>
                </p>
            )
        ) : (
            <Loading />
        )
    }
}
FunnelViz.propTypes = {
    funnel: PropTypes.object,
    filters: PropTypes.shape({ funnel_id: PropTypes.number }),
}
