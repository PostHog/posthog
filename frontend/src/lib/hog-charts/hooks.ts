import { useEffect, useRef } from 'react'

import type { ChartConfiguration, ChartType } from 'lib/Chart'

import { buildTooltipContext } from './adapter'
import type { BaseChartProps, ClickEvent, Series, TooltipContext } from './types'

/**
 * Internal hook that creates and manages a Chart.js instance with integrated
 * tooltip support.
 *
 * - Destroys and recreates the chart when `config` changes (value equality
 *   via JSON.stringify to avoid unnecessary rebuilds).
 * - Guards against multiple charts on the same canvas (React strict mode).
 * - Wires up click handlers that translate Chart.js events into `ClickEvent`.
 * - Wires up the external tooltip handler when `tooltip.render` is provided,
 *   bridging Chart.js tooltip callbacks into `TooltipContext`.
 */
export function useHogChart<TType extends ChartType = ChartType>(
    config: ChartConfiguration<TType> | null,
    props: BaseChartProps,
    tooltipCallbacks?: {
        onShow: (context: TooltipContext) => void
        onHide: () => void
    }
): {
    canvasRef: React.RefObject<HTMLCanvasElement>
    containerRef: React.RefObject<HTMLDivElement>
} {
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const chartRef = useRef<InstanceType<typeof import('lib/Chart').Chart> | null>(null)
    const configKey = JSON.stringify(config)

    // Keep callbacks in refs so the Chart.js handler always calls the latest version
    const tooltipCallbacksRef = useRef(tooltipCallbacks)
    tooltipCallbacksRef.current = tooltipCallbacks
    const propsRef = useRef(props)
    propsRef.current = props

    useEffect(() => {
        if (!canvasRef.current || !config) {
            return
        }

        const initChart = async (): Promise<void> => {
            const { Chart } = await import('lib/Chart')
            const canvas = canvasRef.current
            if (!canvas) {
                return
            }

            // Destroy any existing chart on this canvas
            const existing = Chart.getChart(canvas)
            if (existing) {
                existing.destroy()
            }
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }

            const mergedConfig = { ...config }
            const mergedOptions = { ...(mergedConfig.options as Record<string, unknown>) }

            // -- Inject external tooltip handler --
            const hasCustomTooltip = !!propsRef.current.tooltip?.render
            if (hasCustomTooltip) {
                const plugins = { ...(mergedOptions.plugins as Record<string, unknown>) }
                const tooltipOpts = { ...(plugins.tooltip as Record<string, unknown>) }

                tooltipOpts.external = (ctx: { tooltip: unknown; chart: { canvas: HTMLCanvasElement } }) => {
                    const tooltipModel = ctx.tooltip as {
                        opacity: number
                        title?: string[]
                        dataPoints?: Array<{
                            datasetIndex: number
                            dataIndex: number
                            raw: number
                            dataset: {
                                label?: string
                                borderColor?: string | string[]
                                _hogMeta?: Record<string, unknown>
                            }
                        }>
                        caretX: number
                        caretY: number
                    }

                    const meta = (mergedOptions._hogTooltipMeta as { seriesData: Series[] }) ?? { seriesData: [] }
                    const chartBounds = ctx.chart.canvas.getBoundingClientRect()
                    const context = buildTooltipContext(tooltipModel, chartBounds, meta.seriesData)

                    if (context) {
                        tooltipCallbacksRef.current?.onShow(context)
                    } else {
                        tooltipCallbacksRef.current?.onHide()
                    }
                }

                plugins.tooltip = tooltipOpts
                mergedOptions.plugins = plugins
            }

            // -- Inject onClick handler --
            if (propsRef.current.onClick) {
                const hogMeta = (mergedOptions._hogTooltipMeta as { seriesData: Series[] }) ?? { seriesData: [] }
                mergedOptions.onClick = (
                    _event: unknown,
                    elements: Array<{ datasetIndex: number; index: number }>
                ) => {
                    if (elements.length > 0) {
                        const el = elements[0]
                        const dataset = config.data.datasets[el.datasetIndex]
                        const seriesMeta = hogMeta.seriesData[el.datasetIndex]?.meta
                        const clickEvent: ClickEvent = {
                            seriesIndex: el.datasetIndex,
                            pointIndex: el.index,
                            value: (dataset.data as number[])[el.index],
                            label: String((config.data.labels as string[])?.[el.index] ?? ''),
                            seriesLabel: String(dataset.label ?? ''),
                            meta: seriesMeta,
                        }
                        propsRef.current.onClick?.(clickEvent)
                    }
                }
            }

            mergedConfig.options = mergedOptions as never

            chartRef.current = new Chart(canvas, mergedConfig as ChartConfiguration) as never
        }

        void initChart()

        return () => {
            chartRef.current?.destroy()
            chartRef.current = null
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [configKey])

    return { canvasRef, containerRef }
}
