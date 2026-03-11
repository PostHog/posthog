import { Chart, registerables } from 'chart.js'
import type { ChartConfiguration, ChartType } from 'chart.js'
import annotationPlugin from 'chartjs-plugin-annotation'
import ChartDataLabels from 'chartjs-plugin-datalabels'
import ChartjsPluginStacked100 from 'chartjs-plugin-stacked100'
import chartTrendline from 'chartjs-plugin-trendline'
import type React from 'react'
import { useEffect, useRef } from 'react'

import { buildTooltipContext } from './adapters'
import type { HogTooltipMeta } from './adapters/common'
import type { BaseChartProps, ClickEvent, LineProps, TooltipContext } from './types'

let pluginsRegistered = false
function ensurePluginsRegistered(): void {
    if (!pluginsRegistered) {
        if (registerables) {
            Chart.register(...registerables)
        }
        Chart.register(annotationPlugin)
        Chart.register(ChartjsPluginStacked100)
        pluginsRegistered = true
    }
}

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
    ensurePluginsRegistered()
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const chartRef = useRef<InstanceType<typeof Chart> | null>(null)
    const configKey = JSON.stringify(config)

    const tooltipCallbacksRef = useRef(tooltipCallbacks)
    tooltipCallbacksRef.current = tooltipCallbacks
    const propsRef = useRef(props)
    propsRef.current = props

    useEffect(() => {
        if (!canvasRef.current || !config) {
            return
        }

        const canvas = canvasRef.current

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
                            _hogHideFromTooltip?: boolean
                        }
                    }>
                    caretX: number
                    caretY: number
                }

                const meta = mergedOptions._hogTooltipMeta as HogTooltipMeta
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

        mergedOptions.onHover = (
            event: { native?: Event },
            elements: Array<{ datasetIndex: number; index: number }>
        ) => {
            if (event.native) {
                const target = event.native.target as HTMLElement | null
                if (target) {
                    target.style.cursor = propsRef.current.onClick && elements.length > 0 ? 'pointer' : 'default'
                }
            }
            const currentProps = propsRef.current as LineProps
            if (currentProps.onHighlightChange) {
                const newIdx = elements.length > 0 ? elements[0].datasetIndex : null
                currentProps.onHighlightChange(newIdx)
            }
        }

        if (propsRef.current.onClick) {
            const hogMeta = mergedOptions._hogTooltipMeta as HogTooltipMeta
            mergedOptions.onClick = (
                event: { native?: Event },
                _elements: unknown[],
                chart: {
                    getElementsAtEventForMode: (
                        e: Event,
                        mode: string,
                        opts: object,
                        useFinalPosition: boolean
                    ) => Array<{ datasetIndex: number; index: number }>
                }
            ) => {
                if (!event.native) {
                    return
                }
                const elements = chart.getElementsAtEventForMode(event.native, 'index', { intersect: false }, true)
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

        const perChartPlugins: unknown[] = [ChartDataLabels]
        const hasTrendline = (mergedConfig.data?.datasets ?? []).some(
            (ds: Record<string, unknown>) => !!ds.trendlineLinear
        )
        if (hasTrendline) {
            perChartPlugins.push(chartTrendline)
        }
        ;(mergedConfig as Record<string, unknown>).plugins = perChartPlugins

        chartRef.current = new Chart(canvas, mergedConfig as ChartConfiguration) as never

        return () => {
            chartRef.current?.destroy()
            chartRef.current = null
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [configKey])

    return { canvasRef, containerRef }
}
