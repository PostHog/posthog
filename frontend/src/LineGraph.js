import React, { Component } from 'react'
import Chart from "chart.js";
import PropTypes from 'prop-types';
let myLineChart;

//--Chart Style Options--//
// Chart.defaults.global.defaultFontFamily = "'PT Sans', sans-serif"
Chart.defaults.global.legend.display = false;
//--Chart Style Options--//

export default class LineGraph extends Component {
    chartRef = React.createRef();

    componentDidMount() {
        this.buildChart();
    }

    componentDidUpdate() {
        this.buildChart();
    }

    buildChart = () => {
        const myChartRef = this.chartRef.current.getContext("2d");
        const { datasets, labels, options } = this.props;

        if (typeof myLineChart !== "undefined") myLineChart.destroy();
        let colors = ['blue', 'orange', 'green', 'red', 'purple', 'gray'];
        let getVar = (variable) => getComputedStyle(document.body).getPropertyValue('--' + variable)

        myLineChart = new Chart(myChartRef, {
            type: "line",
            data: {
                //Bring in data
                labels: labels,
                datasets: datasets.map((dataset, index) => ({borderColor: getVar(colors[index]), fill: false, ...dataset}))
            },
            options: {
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
                            var label = data.datasets[tooltipItem.datasetIndex].label || '';
                            return label
                        }
                    }
                },
                hover: {
                    mode: 'index'
                },
                scales: {
                    xAxes: [{
                        display: true,
                        gridLines: { lineWidth: 0 },
                        ticks: {autoSkip: true},
            
                    }],
                    yAxes: [{
                        display: true,
                        ticks: {
                            autoSkip: true,
                        }
                    }]
                }
                            
            }
        });

    }

    render() {

        return (
            <div style={{height: '70vh'}}> 
                <canvas
                    id="myChart"
                    ref={this.chartRef}
                />
            </div>
        )
    }
}
LineGraph.propTypes = {
    datasets: PropTypes.array.isRequired,
    labels: PropTypes.array.isRequired,
    options: PropTypes.object.isRequired
}