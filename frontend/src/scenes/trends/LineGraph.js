import React, { Component } from 'react'
import Chart from 'chart.js'
import PropTypes from 'prop-types'

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

    buildChart = () => {
        const myChartRef = this.chartRef.current.getContext('2d')
        const { datasets, labels, options } = this.props

        if (typeof this.myLineChart !== 'undefined') this.myLineChart.destroy()
        let colors = ['blue', 'orange', 'green', 'red', 'purple', 'gray']
        let getVar = variable => getComputedStyle(document.body).getPropertyValue('--' + variable)

        this.myLineChart = new Chart(myChartRef, {
            type: this.props.type || 'line',
            data: {
                //Bring in data
                labels: labels,
                datasets: datasets.map((dataset, index) => ({
                    borderColor: getVar(colors[index]),
                    backgroundColor:
                        (this.props.type == 'bar' || this.props.type == 'doughnut') && getVar(colors[index]),
                    fill: false,
                    borderWidth: 1,
                    ...dataset,
                })),
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
                                      var label = data.datasets[tooltipItem.datasetIndex].label || ''
                                      return label + ' - ' + tooltipItem.yLabel.toLocaleString()
                                  },
                              },
                          },
                          hover: {
                              mode: 'nearest',
                          },
                          scales: {
                              xAxes: [
                                  {
                                      display: true,
                                      gridLines: { lineWidth: 0 },
                                      ticks: { autoSkip: true },
                                  },
                              ],
                              yAxes: [
                                  {
                                      display: true,
                                      ticks: {
                                          autoSkip: true,
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
