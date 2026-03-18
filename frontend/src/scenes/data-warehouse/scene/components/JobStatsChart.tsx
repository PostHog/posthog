import { useMemo } from 'react'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType, DataWarehouseJobStats } from '~/types'

interface JobStatsChartProps {
    jobStats: DataWarehouseJobStats
}

export function JobStatsChart({ jobStats }: JobStatsChartProps): JSX.Element {
    const { xData, yData } = useMemo(() => {
        if (!jobStats?.breakdown) {
            return { xData: null, yData: [] }
        }

        const timestamps = Object.keys(jobStats.breakdown).sort()
        const successData = timestamps.map((ts) => jobStats.breakdown[ts].successful)
        const failedData = timestamps.map((ts) => jobStats.breakdown[ts].failed)

        const isHourly = jobStats.days === 1

        const labels = timestamps.map((ts) => {
            const d = new Date(ts)
            if (isHourly) {
                return d.toLocaleTimeString('en-US', { hour: 'numeric', hour12: true })
            }
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        })

        const successColor = getComputedStyle(document.body).getPropertyValue('--success').trim() || '#388600'
        const dangerColor = getComputedStyle(document.body).getPropertyValue('--danger').trim() || '#db3707'

        return {
            xData: {
                column: {
                    name: 'timestamp',
                    type: {
                        name: 'STRING' as const,
                        isNumerical: false,
                    },
                    label: 'Time',
                    dataIndex: 0,
                },
                data: labels,
            },
            yData: [
                {
                    column: {
                        name: 'successful',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Successful',
                        dataIndex: 0,
                    },
                    data: successData,
                    settings: {
                        display: {
                            color: successColor,
                            displayType: 'bar' as const,
                        },
                    },
                },
                {
                    column: {
                        name: 'failed',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Failed',
                        dataIndex: 1,
                    },
                    data: failedData,
                    settings: {
                        display: {
                            color: dangerColor,
                            displayType: 'bar' as const,
                        },
                    },
                },
            ],
        }
    }, [jobStats])

    if (!jobStats?.breakdown) {
        return <div className="relative h-full min-h-48 flex items-center justify-center">No data available</div>
    }

    return (
        <LineGraph
            className="h-full min-h-80"
            xData={xData}
            yData={yData}
            visualizationType={ChartDisplayType.ActionsStackedBar}
            chartSettings={{
                stackBars100: false,
            }}
        />
    )
}
