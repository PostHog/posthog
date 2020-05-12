import React, { Component } from 'react'
import Chart from 'chart.js'
import PropTypes from 'prop-types'
import { formatFilterName } from '~/lib/utils'
import _ from 'lodash'

//--Chart Style Options--//
// Chart.defaults.global.defaultFontFamily = "'PT Sans', sans-serif"
Chart.defaults.global.legend.display = false
//--Chart Style Options--//

export class LineGraph extends Component {
    chartRef = React.createRef()

    componentDidMount() {
        this.buildChart()
    }

    componentDidUpdate(prevProps) {
        if (prevProps.datasets !== this.props.datasets) {
            this.buildChart()
        }
    }

    processDataset = (dataset, index) => {
        let colors = ['blue', 'orange', 'green', 'red', 'purple', 'gray']
        let getVar = variable => getComputedStyle(document.body).getPropertyValue('--' + variable)
        return {
            borderColor: getVar(colors[index]),
            backgroundColor: (this.props.type == 'bar' || this.props.type == 'doughnut') && getVar(colors[index]),
            fill: false,
            borderWidth: 1,
            pointHitRadius: 8,
            ...dataset,
        }
    }

    buildChart = () => {
        const myChartRef = this.chartRef.current.getContext('2d')
        let { datasets, labels } = this.props

        if (typeof this.myLineChart !== 'undefined') this.myLineChart.destroy()
        const _this = this
        // if chart is line graph, make duplicate lines and overlay to show dotted lines
        datasets =
            !this.props.type || this.props.type == 'line'
                ? [
                      ...datasets.map((dataset, index) => {
                          let datasetCopy = Object.assign({}, dataset)
                          let data = [...dataset.data]
                          let labels = [...dataset.labels]
                          let days = [...dataset.days]
                          data.pop()
                          labels.pop()
                          days.pop()
                          datasetCopy.data = data
                          datasetCopy.labels = labels
                          datasetCopy.days = days
                          return this.processDataset(datasetCopy, index)
                      }),
                      ...datasets.map((dataset, index) => {
                          let datasetCopy = Object.assign({}, dataset)
                          let datasetLength = datasetCopy.data.length
                          datasetCopy.dotted = true

                          // if last date is still active show dotted line
                          if (this.props.isInProgress) {
                              datasetCopy.borderDash = [10, 10]
                          }

                          datasetCopy.data =
                              datasetCopy.data.length > 2
                                  ? datasetCopy.data.map((datum, index) =>
                                        index == datasetLength - 1 || index == datasetLength - 2 ? datum : null
                                    )
                                  : datasetCopy.data
                          return this.processDataset(datasetCopy, index)
                      }),
                  ]
                : datasets.map((dataset, index) => this.processDataset(dataset, index))

        this.myLineChart = new Chart(myChartRef, {
            type: this.props.type || 'line',
            data: {
                //Bring in data
                labels: labels,
                datasets: datasets,
            },
            options:
                this.props.type !== 'doughnut'
                    ? {
                          responsive: true,
                          maintainAspectRatio: false,
                          scaleShowHorizontalLines: false,
                          tooltips: {
                              enabled: true,
                              intersect: false,
                              mode: 'nearest',
                              bodySpacing: 5,
                              yPadding: 10,
                              xPadding: 10,
                              caretPadding: 0,
                              displayColors: false,
                              backgroundColor: '#1dc9b7',
                              titleFontColor: '#ffffff',
                              labelFontSize: 23,
                              cornerRadius: 4,
                              fontSize: 16,
                              footerSpacing: 0,
                              titleSpacing: 0,
                              callbacks: {
                                  label: function(tooltipItem, data) {
                                      let entityData = data.datasets[tooltipItem.datasetIndex]
                                      if (entityData.dotted && !(tooltipItem.index == entityData.data.length - 1))
                                          return null
                                      var label = entityData.chartLabel || entityData.label || ''
                                      if (entityData.action.properties && !_.isEmpty(entityData.action.properties)) {
                                          label += ' ('
                                          Object.entries(entityData.action.properties).forEach(([key, val], index) => {
                                              if (index > 0) label += ', '
                                              label += formatFilterName(key).split(' ')[1] + ' ' + val
                                          })
                                          label += ')'
                                      }

                                      return label + ' - ' + tooltipItem.yLabel.toLocaleString()
                                  },
                              },
                          },
                          hover: {
                              mode: 'nearest',
                              onHover(e) {
                                  if (_this.props.onClick) {
                                      const point = this.getElementAtEvent(e)
                                      if (point.length) e.target.style.cursor = 'pointer'
                                      else e.target.style.cursor = 'default'
                                  }
                              },
                          },
                          scales: {
                              xAxes: [
                                  {
                                      display: true,
                                      gridLines: { lineWidth: 0 },
                                      ticks: { autoSkip: true, beginAtZero: true, min: 0 },
                                  },
                              ],
                              yAxes: [
                                  {
                                      display: true,
                                      ticks: {
                                          autoSkip: true,
                                          beginAtZero: true,
                                          min: 0,
                                      },
                                  },
                              ],
                          },
                          onClick: (event, [point]) => {
                              if (point && this.props.onClick) {
                                  const dataset = datasets[point._datasetIndex]
                                  this.props.onClick({
                                      point,
                                      dataset,
                                      index: point._index,
                                      label:
                                          typeof point._index !== 'undefined' && dataset.labels
                                              ? dataset.labels[point._index]
                                              : undefined,
                                      day:
                                          typeof point._index !== 'undefined' && dataset.days
                                              ? dataset.days[point._index]
                                              : undefined,
                                      value:
                                          typeof point._index !== 'undefined' && dataset.data
                                              ? dataset.data[point._index]
                                              : undefined,
                                  })
                              }
                          },
                      }
                    : {
                          responsive: true,
                          maintainAspectRatio: false,
                          hover: { mode: 'index' },
                      },
        })
    }

    render() {
        return (
            <div className="graph-container">
                <canvas ref={this.chartRef} />
            </div>
        )
    }
}
LineGraph.propTypes = {
    datasets: PropTypes.arrayOf(PropTypes.shape({ label: PropTypes.string, count: PropTypes.number })).isRequired,
    labels: PropTypes.array.isRequired,
    options: PropTypes.object,
    type: PropTypes.string,
    onClick: PropTypes.func,
}
