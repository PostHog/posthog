import { useActions, useValues } from 'kea'
import { Chart, ChartConfiguration } from 'lib/Chart'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useEffect } from 'react'
import { modalsLogic } from 'scenes/experiments/modalsLogic'

const DELTA = [0.16, 0.17, 0.15, 0.16, 0.14, 0.15, 0.145, 0.15, 0.155, 0.148, 0.15, 0.147, 0.152, 0.15]
const UPPER_BOUND = [0.26, 0.27, 0.24, 0.24, 0.21, 0.21, 0.2, 0.2, 0.195, 0.183, 0.182, 0.177, 0.182, 0.18]
const LOWER_BOUND = [0.06, 0.07, 0.06, 0.08, 0.07, 0.09, 0.09, 0.1, 0.115, 0.113, 0.118, 0.117, 0.122, 0.12]

export const VariantDeltaTimeseries = (): JSX.Element => {
    const { closeVariantDeltaTimeseriesModal } = useActions(modalsLogic)
    const { isVariantDeltaTimeseriesModalOpen } = useValues(modalsLogic)

    useEffect(() => {
        if (isVariantDeltaTimeseriesModalOpen) {
            setTimeout(() => {
                const ctx = document.getElementById('variantDeltaChart') as HTMLCanvasElement
                if (!ctx) {
                    console.error('Canvas element not found')
                    return
                }

                const existingChart = Chart.getChart(ctx)
                if (existingChart) {
                    existingChart.destroy()
                }

                ctx.style.width = '100%'
                ctx.style.height = '100%'

                const data = {
                    labels: [
                        'Day 1',
                        'Day 2',
                        'Day 3',
                        'Day 4',
                        'Day 5',
                        'Day 6',
                        'Day 7',
                        'Day 8',
                        'Day 9',
                        'Day 10',
                        'Day 11',
                        'Day 12',
                        'Day 13',
                        'Day 14',
                    ],
                    datasets: [
                        {
                            label: 'Upper Bound',
                            data: UPPER_BOUND,
                            borderColor: 'rgba(200, 200, 200, 1)',
                            fill: false,
                            tension: 0,
                            pointRadius: 0,
                        },
                        {
                            label: 'Lower Bound',
                            data: LOWER_BOUND,
                            borderColor: 'rgba(200, 200, 200, 1)',
                            fill: '-1',
                            backgroundColor: 'rgba(200, 200, 200, 0.2)',
                            tension: 0,
                            pointRadius: 0,
                        },
                        {
                            label: 'Delta',
                            data: DELTA,
                            borderColor: 'rgba(0, 100, 255, 1)',
                            borderWidth: 2,
                            fill: false,
                            tension: 0,
                            pointRadius: 0,
                        },
                    ],
                }

                const config: ChartConfiguration = {
                    type: 'line',
                    data: data,
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {
                            intersect: false,
                            mode: 'nearest',
                            axis: 'x',
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                grid: {
                                    display: false,
                                },
                                ticks: {
                                    count: 6,
                                    callback: (value) => `${(Number(value) * 100).toFixed(1)}%`,
                                },
                            },
                        },
                        plugins: {
                            legend: {
                                display: false,
                            },
                            tooltip: {
                                callbacks: {
                                    labelPointStyle: function () {
                                        return {
                                            pointStyle: 'circle',
                                            rotation: 0,
                                        }
                                    },
                                },
                                usePointStyle: true,
                                boxWidth: 16,
                                boxHeight: 1,
                            },
                            // @ts-expect-error Types of library are out of date
                            crosshair: false,
                        },
                    },
                }

                new Chart(ctx, config)
            }, 0)
        }
    }, [isVariantDeltaTimeseriesModalOpen])

    return (
        <LemonModal
            isOpen={isVariantDeltaTimeseriesModalOpen}
            onClose={() => {
                closeVariantDeltaTimeseriesModal()
            }}
            width={800}
            title="Variant performance over time"
            footer={
                <LemonButton form="secondary-metric-modal-form" type="secondary" onClick={() => {}}>
                    Close
                </LemonButton>
            }
        >
            <div className="relative h-[400px]">
                <canvas id="variantDeltaChart" />
            </div>
        </LemonModal>
    )
}
