import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { LineChart, ReferenceLines, useChartTheme } from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { FunnelAlertPreview } from 'products/alerts/frontend/logic/funnelAlertPreview'
import { HogQLAlertPreview } from 'products/alerts/frontend/logic/hogqlAlertPreview'
import { MetricsAlertPreviewSeries } from 'products/alerts/frontend/logic/metricsAlertPreview'
import {
    deriveTrendsAlertPreviewSeries,
    deriveTrendsBreakdownAlertPreview,
    TrendsAlertPreviewSeries,
} from 'products/alerts/frontend/logic/trendsAlertPreview'
import {
    isFunnelsAlertConfig,
    isHogQLAlertConfig,
    isMetricsAlertConfig,
    isTrendsAlertConfig,
} from 'products/alerts/frontend/types'

import { FunnelAlertPreviewBanner } from './AlertDefinitionFields'
import { AlertThresholdLine, shouldUseLogScale, thresholdReferenceLines } from './AlertPreviewCard.utils'
import { HogQLAlertPreviewBanner } from './HogQLAlertPreview'

const handleChartError = makeChartErrorHandler('alerts-preview-chart')

interface AlertPreviewChartSeries {
    key: string
    label: string
    data: number[]
}

function AlertPreviewChart({
    series,
    labels,
    referenceLines,
    relative,
    useLogScale,
}: {
    series: AlertPreviewChartSeries[]
    labels?: string[]
    referenceLines: AlertThresholdLine[]
    relative: boolean
    useLogScale: boolean
}): JSX.Element {
    const theme = useChartTheme()
    return (
        <div className="w-full h-24 flex flex-col">
            <LineChart
                series={series}
                labels={labels ?? series[0]?.data?.map((_, index) => String(index)) ?? []}
                theme={theme}
                config={{
                    hideXAxis: true,
                    // The value axis only appears in relative mode, where it can dip below zero;
                    // absolute previews stay axis-less and compact like the old sparkline.
                    hideYAxis: !relative,
                    floatBaseline: relative,
                    yScaleType: useLogScale ? 'log' : 'linear',
                    tooltip: { valueFormatter: (value) => humanFriendlyNumber(value) },
                }}
                onError={handleChartError}
            >
                <ReferenceLines lines={referenceLines.map((line) => ({ ...line, variant: 'alert' as const }))} />
            </LineChart>
        </div>
    )
}

export interface AlertPreviewCardProps {
    alertForm: AlertFormType
    trendsValues: number[] | null
    trendsLabels?: string[] | null
    isBreakdown?: boolean
    trendsBreakdownSeries?: AlertPreviewChartSeries[] | null
    funnelPreview: FunnelAlertPreview | null
    hogqlPreview: HogQLAlertPreview | null
    metricsPreview?: MetricsAlertPreviewSeries | null
    metricsPreviewFailed?: boolean
    onRetryMetricsPreview?: () => void
    checkPreview?: TrendsAlertPreviewSeries
    previewHistoryTooShort?: boolean
    // Keeps the card visible with a skeleton while data loads instead of popping in once it arrives.
    loading?: boolean
}

export function AlertPreviewCard({
    alertForm,
    trendsValues,
    trendsLabels,
    isBreakdown,
    trendsBreakdownSeries,
    funnelPreview,
    hogqlPreview,
    metricsPreview,
    metricsPreviewFailed,
    onRetryMetricsPreview,
    checkPreview,
    previewHistoryTooShort,
    loading,
}: AlertPreviewCardProps): JSX.Element {
    const config = alertForm.config
    const conditionType = alertForm.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE
    const thresholdType = alertForm.threshold?.configuration?.type ?? InsightThresholdType.ABSOLUTE
    const trendsPreview = trendsValues
        ? deriveTrendsAlertPreviewSeries(trendsValues, trendsLabels ?? undefined, conditionType, thresholdType)
        : null
    const isBreakdownPreview = isTrendsAlertConfig(config) && isBreakdown
    const metricsSeries = isMetricsAlertConfig(config) && checkPreview === undefined ? metricsPreview : null
    const isMultiSeriesPreview = isBreakdownPreview || !!metricsSeries
    const referenceLines = thresholdReferenceLines(alertForm)
    const useLogScale = Boolean(
        !isBreakdownPreview && trendsPreview && shouldUseLogScale(trendsPreview.values, referenceLines)
    )
    const checkPreviewValues = checkPreview?.values
    const breakdownPreview = deriveTrendsBreakdownAlertPreview(
        metricsSeries ? metricsSeries.rows : (trendsBreakdownSeries ?? undefined),
        metricsSeries ? metricsSeries.labels : (trendsLabels ?? undefined),
        conditionType,
        thresholdType
    )
    // A row carries `NaN` on the intervals it has no comparison for, so count only drawable points.
    const breakdownPreviewValues =
        breakdownPreview?.rows.flatMap((row) => row.data).filter((value) => Number.isFinite(value)) ?? []
    const breakdownUseLogScale = shouldUseLogScale(breakdownPreviewValues, referenceLines)
    const isUnconfiguredAbsoluteThreshold =
        !alertForm.detector_config &&
        alertForm.condition?.type === AlertConditionType.ABSOLUTE_VALUE &&
        alertForm.threshold?.configuration?.type === InsightThresholdType.ABSOLUTE &&
        referenceLines.length === 0
    const isAnomalyDetectionWithoutVisibleData =
        !loading &&
        !!alertForm.detector_config &&
        isTrendsAlertConfig(config) &&
        !trendsValues?.some((value) => value !== 0)

    let body: JSX.Element | null = null
    if (isMetricsAlertConfig(config) && checkPreview === undefined && metricsPreviewFailed && !loading) {
        body = (
            <div className="flex h-24 flex-col items-center justify-center gap-2 rounded border border-dashed border-border text-sm text-muted">
                <span>Couldn't load metric data for the preview.</span>
                <LemonButton size="small" type="secondary" onClick={onRetryMetricsPreview}>
                    Try again
                </LemonButton>
            </div>
        )
    } else if (isUnconfiguredAbsoluteThreshold) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                Set less than or more than to preview this alert.
            </div>
        )
    } else if (previewHistoryTooShort && !loading) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                The insight's date range is too short to preview this delay. The alert loads more history when it runs.
            </div>
        )
    } else if (isMultiSeriesPreview && breakdownPreview && breakdownPreviewValues.length > 0) {
        body = (
            <AlertPreviewChart
                series={breakdownPreview.rows}
                labels={breakdownPreview.labels}
                referenceLines={referenceLines}
                relative={conditionType !== AlertConditionType.ABSOLUTE_VALUE}
                useLogScale={breakdownUseLogScale}
            />
        )
    } else if (isMultiSeriesPreview && !loading) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                {isBreakdownPreview ? 'No activity to preview across breakdown values.' : 'No metric data to preview.'}
            </div>
        )
    } else if (checkPreviewValues && checkPreviewValues.length > 0) {
        body = (
            <AlertPreviewChart
                series={[{ key: 'preview', label: 'Value', data: checkPreviewValues }]}
                labels={checkPreview.labels}
                referenceLines={referenceLines}
                relative={checkPreview.relative}
                useLogScale={false}
            />
        )
    } else if (checkPreview !== undefined) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                No evaluations available yet.
            </div>
        )
    } else if (isAnomalyDetectionWithoutVisibleData) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                No activity to preview for this series.
            </div>
        )
    } else if (isTrendsAlertConfig(config) && trendsPreview && trendsPreview.values.length > 0) {
        body = (
            <AlertPreviewChart
                series={[{ key: 'preview', label: 'Value', data: trendsPreview.values }]}
                labels={trendsPreview.labels}
                referenceLines={referenceLines}
                relative={trendsPreview.relative}
                useLogScale={useLogScale}
            />
        )
    } else if (isFunnelsAlertConfig(config) && funnelPreview) {
        body = <FunnelAlertPreviewBanner preview={funnelPreview} />
    } else if (isHogQLAlertConfig(config) && hogqlPreview) {
        body = <HogQLAlertPreviewBanner preview={hogqlPreview} conditionType={alertForm.condition?.type} />
    }

    if (!body) {
        if (loading) {
            return (
                <div className="space-y-2">
                    <div className="flex items-center gap-1.5 text-sm font-medium">
                        <span>Preview</span>
                    </div>
                    <LemonSkeleton className="h-16 w-full" />
                </div>
            )
        }
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                No insight data available to preview.
            </div>
        )
    }

    let lastValue: number | null = null
    if (!isBreakdownPreview && checkPreviewValues?.length) {
        lastValue = checkPreviewValues[checkPreviewValues.length - 1]
    } else if (isTrendsAlertConfig(config) && trendsPreview?.values.length && !isBreakdownPreview) {
        lastValue = trendsPreview.values[trendsPreview.values.length - 1]
    }

    let previewTooltip =
        'What this alert is watching right now. The dashed lines are your thresholds; points crossing them would fire.'
    if (isBreakdownPreview) {
        previewTooltip = 'Every breakdown value is shown. The dashed lines are your thresholds.'
    } else if (checkPreview !== undefined) {
        previewTooltip = 'Values recorded by recent alert evaluations.'
    } else if (metricsSeries && metricsSeries.rows.length > 1) {
        previewTooltip = 'Every series the query returns is checked. The dashed lines are your thresholds.'
    }
    let previewTitle = 'Preview'
    if (isBreakdownPreview) {
        previewTitle = 'All breakdown values'
    } else if (checkPreview !== undefined) {
        previewTitle = 'Recent evaluations'
    } else if (metricsSeries && metricsSeries.rows.length > 1) {
        previewTitle = 'All series'
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                    <span>{previewTitle}</span>
                    <Tooltip title={previewTooltip} delayMs={0}>
                        <IconInfo className="text-muted size-3.5" />
                    </Tooltip>
                </div>
                <div className="flex items-center gap-2">
                    {useLogScale ? (
                        <Tooltip title="A log scale keeps thresholds with very different values visually distinct.">
                            <LemonTag type="default" className="m-0">
                                Log scale
                            </LemonTag>
                        </Tooltip>
                    ) : null}
                    {lastValue != null ? (
                        <LemonTag type="default" className="m-0">
                            {checkPreview?.relative || trendsPreview?.relative ? 'Latest change:' : 'Latest:'}
                            <strong className="ml-1">{humanFriendlyNumber(lastValue)}</strong>
                        </LemonTag>
                    ) : null}
                </div>
            </div>
            {body}
        </div>
    )
}
