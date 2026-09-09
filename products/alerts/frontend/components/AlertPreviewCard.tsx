import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { LineChart, ReferenceLines, useChartTheme } from '@posthog/quill-charts'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    AlertConditionType,
    ForecastConditionType,
    InsightsThresholdBounds,
    InsightThresholdType,
} from '~/queries/schema/schema-general'

import { ForecastSimulateResponseApi } from 'products/alerts/frontend/generated/api.schemas'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { FunnelAlertPreview } from 'products/alerts/frontend/logic/funnelAlertPreview'
import { HogQLAlertPreview } from 'products/alerts/frontend/logic/hogqlAlertPreview'
import {
    deriveTrendsAlertPreviewSeries,
    deriveTrendsBreakdownAlertPreview,
    TrendsAlertPreviewSeries,
} from 'products/alerts/frontend/logic/trendsAlertPreview'
import { isFunnelsAlertConfig, isHogQLAlertConfig, isTrendsAlertConfig } from 'products/alerts/frontend/types'
import { ForecastPreview } from 'products/alerts/frontend/views/ForecastPreview'
import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

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
    checkPreview?: TrendsAlertPreviewSeries
    forecast?: { result: ForecastSimulateResponseApi; thresholdBounds: InsightsThresholdBounds | null }
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
    checkPreview,
    forecast,
    loading,
}: AlertPreviewCardProps): JSX.Element {
    const config = alertForm.config
    const conditionType = alertForm.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE
    const thresholdType = alertForm.threshold?.configuration?.type ?? InsightThresholdType.ABSOLUTE
    const trendsPreview = trendsValues
        ? deriveTrendsAlertPreviewSeries(trendsValues, trendsLabels ?? undefined, conditionType, thresholdType)
        : null
    const isBreakdownPreview = isTrendsAlertConfig(config) && isBreakdown
    // Keyed on the mode, not on a stored result: the card sits in forecast mode before the first
    // run and after every edit, and its header has to describe the forecast even with no chart yet.
    const isForecastMode = !!alertForm.forecast_config
    const forecastReadsThreshold =
        !alertForm.forecast_config || alertForm.forecast_config.condition === ForecastConditionType.FUTURE_BREACH
    const referenceLines = forecastReadsThreshold ? thresholdReferenceLines(alertForm) : []
    const useLogScale = Boolean(
        !isBreakdownPreview && trendsPreview && shouldUseLogScale(trendsPreview.values, referenceLines)
    )
    const checkPreviewValues = checkPreview?.values
    const breakdownPreview = deriveTrendsBreakdownAlertPreview(
        trendsBreakdownSeries ?? undefined,
        trendsLabels ?? undefined,
        conditionType,
        thresholdType
    )
    // A row carries `NaN` on the intervals it has no comparison for, so count only drawable points.
    const breakdownPreviewValues =
        breakdownPreview?.rows.flatMap((row) => row.data).filter((value) => Number.isFinite(value)) ?? []
    const breakdownUseLogScale = shouldUseLogScale(breakdownPreviewValues, referenceLines)
    const isUnconfiguredAbsoluteThreshold =
        !alertForm.detector_config &&
        forecastReadsThreshold &&
        alertForm.condition?.type === AlertConditionType.ABSOLUTE_VALUE &&
        alertForm.threshold?.configuration?.type === InsightThresholdType.ABSOLUTE &&
        referenceLines.length === 0
    const isAnomalyDetectionWithoutVisibleData =
        !loading &&
        !!alertForm.detector_config &&
        isTrendsAlertConfig(config) &&
        !trendsValues?.some((value) => value !== 0)

    // The missing-threshold state is reported before the generic forecast prompt. An upcoming-breach
    // forecast with no bound keeps its Preview forecast button disabled until a bound is set, so the
    // generic prompt would name an action the user cannot take yet.
    let body: JSX.Element | null = null
    if (forecast && alertForm.forecast_config) {
        body = (
            <ForecastPreview
                result={forecast.result}
                thresholdBounds={forecast.thresholdBounds}
                forecastConfig={alertForm.forecast_config}
            />
        )
    } else if (isUnconfiguredAbsoluteThreshold) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                Set less than or more than to preview this alert.
            </div>
        )
    } else if (alertForm.forecast_config) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                Run Preview forecast to see it here.
            </div>
        )
    } else if (isBreakdownPreview && breakdownPreview && breakdownPreviewValues.length > 0) {
        body = (
            <AlertPreviewChart
                series={breakdownPreview.rows}
                labels={breakdownPreview.labels}
                referenceLines={referenceLines}
                relative={trendsPreview?.relative ?? false}
                useLogScale={breakdownUseLogScale}
            />
        )
    } else if (isBreakdownPreview && !loading) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                No activity to preview across breakdown values.
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
    }
    let previewTitle = 'Preview'
    if (isBreakdownPreview) {
        previewTitle = 'All breakdown values'
    } else if (checkPreview !== undefined) {
        previewTitle = 'Recent evaluations'
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                    <span>{isForecastMode ? 'Forecast' : previewTitle}</span>
                    <Tooltip
                        title={
                            isForecastMode
                                ? 'History plus the point forecast and a contextual uncertainty range. Run the preview again after changing forecast settings.'
                                : previewTooltip
                        }
                        delayMs={0}
                    >
                        <IconInfo className="text-muted size-3.5" />
                    </Tooltip>
                </div>
                <div className="flex items-center gap-2">
                    {useLogScale && !isForecastMode ? (
                        <Tooltip title="A log scale keeps thresholds with very different values visually distinct.">
                            <LemonTag type="default" className="m-0">
                                Log scale
                            </LemonTag>
                        </Tooltip>
                    ) : null}
                    {/* The trends series still runs to today, so its last point is a partial day. That
                        reads as a real drop next to a forecast, which carries its own summary anyway. */}
                    {lastValue != null && !forecast ? (
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
