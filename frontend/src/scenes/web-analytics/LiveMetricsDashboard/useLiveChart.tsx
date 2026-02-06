import { useEffect, useRef } from 'react'

import { Chart, ChartConfiguration, ChartType } from 'lib/Chart'

interface UseLiveChartOptions<T extends ChartType, D> {
    hasData: boolean
    createConfig: () => ChartConfiguration<T>
    updateData: (chart: Chart<T>, data: D) => void
    data: D
}

interface UseLiveChartResult {
    canvasRef: React.RefObject<HTMLCanvasElement>
}

export const useLiveChart = <T extends ChartType, D>({
    hasData,
    createConfig,
    updateData,
    data,
}: UseLiveChartOptions<T, D>): UseLiveChartResult => {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const chartRef = useRef<Chart<T> | null>(null)

    useEffect(() => {
        if (!hasData) {
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }
            return
        }

        if (!canvasRef.current) {
            return
        }

        if (!chartRef.current) {
            chartRef.current = new Chart(canvasRef.current, createConfig())
            return
        }

        updateData(chartRef.current, data)
        chartRef.current.update('none')
    }, [hasData, data, createConfig, updateData])

    useEffect(() => {
        return () => {
            chartRef.current?.destroy()
            chartRef.current = null
        }
    }, [])

    return { canvasRef }
}

export const TOOLTIP_STYLE = {
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    titleColor: '#fff',
    bodyColor: '#fff',
    padding: 12,
}
