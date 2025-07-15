import { IconCalendar } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDropdown,
    LemonSelect,
    LemonSkeleton,
    Popover,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Chart, ChartDataset, ChartItem } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { humanFriendlyNumber, inStorybookTestRunner } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'

import { ALL_METRIC_TYPES, hogFunctionMetricsLogic, HogFunctionMetricsLogicProps } from './hogFunctionMetricsLogic'

const METRICS_INFO = {
    succeeded: 'Total number of events processed successfully',
    failed: 'Total number of events that had errors during processing',
    filtered: 'Total number of events that were filtered out',
    disabled_temporarily:
        'Total number of events that were skipped due to the destination being temporarily disabled (due to issues such as the destination being down or rate-limited)',
    disabled_permanently:
        'Total number of events that were skipped due to the destination being permanently disabled (due to prolonged issues with the destination)',
}

export function HogFunctionMetrics({ id }: HogFunctionMetricsLogicProps): JSX.Element {
    const logic = hogFunctionMetricsLogic({ id })

    const { filters } = useValues(logic)
    const { type } = useValues(hogFunctionConfigurationLogic({ id }))
    const { setFilters, loadMetrics, loadMetricsTotals } = useActions(logic)

    useEffect(() => {
        loadMetrics()
        loadMetricsTotals()
    }, [])

    return (
        <BindLogic logic={hogFunctionMetricsLogic} props={{ id }}>
            <div className="deprecated-space-y-4">
                <AppMetricsTotals />

                <div className="flex gap-2 items-center">
                    <h2 className="mb-0">Delivery trends</h2>
                    <div className="flex-1" />
                    <LemonDropdown
                        closeOnClickInside={false}
                        matchWidth={false}
                        placement="right-end"
                        overlay={
                            <div className="overflow-hidden deprecated-space-y-2 max-w-100">
                                {ALL_METRIC_TYPES.filter(
                                    ({ value }) => value !== 'fetch' || type !== 'transformation'
                                ).map(({ label, value }) => {
                                    return (
                                        <LemonButton
                                            key={value}
                                            fullWidth
                                            icon={
                                                <LemonCheckbox
                                                    checked={filters?.name?.split(',').includes(value)}
                                                    className="pointer-events-none"
                                                />
                                            }
                                            onClick={() => {
                                                setFilters({
                                                    name: filters?.name?.split(',').includes(value)
                                                        ? filters.name
                                                              .split(',')
                                                              .filter((t) => t != value)
                                                              .join(',')
                                                        : filters.name + ',' + value,
                                                })
                                            }}
                                        >
                                            {label}
                                        </LemonButton>
                                    )
                                })}
                            </div>
                        }
                    >
                        <LemonButton size="small" type="secondary">
                            Filters
                        </LemonButton>
                    </LemonDropdown>
                    <LemonSelect
                        options={[
                            { label: 'Hourly', value: 'hour' },
                            { label: 'Daily', value: 'day' },
                            { label: 'Weekly', value: 'week' },
                        ]}
                        size="small"
                        value={filters.interval}
                        onChange={(value) => setFilters({ interval: value })}
                    />
                    <DateFilter
                        dateTo={filters.before}
                        dateFrom={filters.after}
                        onChange={(from, to) => setFilters({ after: from || undefined, before: to || undefined })}
                        allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar /> {key}
                            </>
                        )}
                    />
                </div>

                <AppMetricsGraph />
            </div>
        </BindLogic>
    )
}

function AppMetricBigNumber({
    label,
    value,
    tooltip,
}: {
    label: string
    value: number | undefined
    tooltip: JSX.Element | string
}): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <div className="flex flex-col flex-1 gap-2 items-center p-2 rounded border bg-surface-primary">
                <div className="text-xs font-bold uppercase">{label.replace(/_/g, ' ')}</div>
                <div className="flex flex-1 items-center mb-2 text-2xl">{humanFriendlyNumber(value ?? 0)}</div>
            </div>
        </Tooltip>
    )
}

function AppMetricsTotals(): JSX.Element {
    const { appMetricsTotals, appMetricsTotalsLoading } = useValues(hogFunctionMetricsLogic)

    return (
        <div className="deprecated-space-y-4">
            <div className="flex flex-wrap gap-2 items-center">
                {Object.entries(METRICS_INFO).map(([key, value]) => (
                    <div key={key} className="flex flex-col flex-1 h-30 min-w-30 max-w-100">
                        {appMetricsTotalsLoading ? (
                            <LemonSkeleton className="w-full h-full" />
                        ) : (
                            <AppMetricBigNumber label={key} value={appMetricsTotals?.totals?.[key]} tooltip={value} />
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}

function AppMetricsGraph(): JSX.Element {
    const { appMetrics, appMetricsLoading } = useValues(hogFunctionMetricsLogic)
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const [popoverContent, setPopoverContent] = useState<JSX.Element | null>(null)
    const [tooltipState, setTooltipState] = useState({ x: 0, y: 0, visible: false })

    useEffect(() => {
        let chart: Chart
        if (canvasRef.current && appMetrics && !inStorybookTestRunner()) {
            chart = new Chart(canvasRef.current?.getContext('2d') as ChartItem, {
                type: 'line',
                data: {
                    labels: appMetrics.labels,
                    datasets: appMetrics.series.map((series) => ({
                        label: series.name,
                        data: series.values,
                        borderColor: '',
                        ...colorConfig(series.name),
                    })),
                },
                options: {
                    scales: {
                        x: {
                            ticks: {
                                maxRotation: 0,
                            },
                            grid: {
                                display: false,
                            },
                        },
                        y: {
                            beginAtZero: true,
                        },
                    },
                    plugins: {
                        // @ts-expect-error Types of library are out of date
                        crosshair: false,
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            enabled: false, // Using external tooltip
                            external({ tooltip, chart }) {
                                setPopoverContent(
                                    <InsightTooltip
                                        embedded
                                        hideInspectActorsSection
                                        // showHeader={!!labels}
                                        altTitle={tooltip.dataPoints[0].label}
                                        seriesData={tooltip.dataPoints.map((dp, i) => ({
                                            id: i,
                                            dataIndex: 0,
                                            datasetIndex: 0,
                                            order: i,
                                            label: dp.dataset.label,
                                            color: dp.dataset.borderColor as string,
                                            count: (dp.dataset.data?.[dp.dataIndex] as number) || 0,
                                        }))}
                                        renderSeries={(value) => value}
                                        renderCount={(count) => humanFriendlyNumber(count)}
                                    />
                                )

                                const position = chart.canvas.getBoundingClientRect()
                                setTooltipState({
                                    x: position.left + tooltip.caretX,
                                    y: position.top + tooltip.caretY,
                                    visible: tooltip.opacity > 0,
                                })
                            },
                        },
                    },
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        axis: 'x',
                        intersect: false,
                    },
                },
            })

            return () => {
                chart?.destroy()
            }
        }
    }, [appMetrics])

    return (
        <div className="relative border rounded p-6 bg-surface-primary h-[50vh]">
            {appMetricsLoading && <SpinnerOverlay />}
            {!!appMetrics && <canvas ref={canvasRef} />}
            <Popover
                visible={tooltipState.visible}
                overlay={popoverContent}
                placement="top"
                padded={false}
                className="pointer-events-none"
            >
                <div
                    className="fixed"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ left: tooltipState.x, top: tooltipState.y }}
                />
            </Popover>
        </div>
    )
}

function colorConfig(name: string): Partial<ChartDataset<'line', any>> {
    let color = ''

    switch (name) {
        case 'succeeded':
            color = getColorVar('success')
            break
        case 'failed':
            color = getColorVar('danger')
            break
        default:
            color = getColorVar('data-color-1')
            break
    }

    return {
        borderColor: color,
        hoverBorderColor: color,
        hoverBackgroundColor: color,
        backgroundColor: color,
        fill: false,
        borderWidth: 2,
        pointRadius: 0,
    }
}
