import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Sparkline, SparklineReferenceLine } from 'lib/components/Sparkline'
import type { AnyScaleOptions } from 'lib/components/Sparkline'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { FunnelAlertPreview } from 'products/alerts/frontend/logic/funnelAlertPreview'
import { HogQLAlertPreview } from 'products/alerts/frontend/logic/hogqlAlertPreview'
import {
    deriveTrendsAlertPreviewSeries,
    TrendsAlertPreviewSeries,
} from 'products/alerts/frontend/logic/trendsAlertPreview'
import { isFunnelsAlertConfig, isHogQLAlertConfig, isTrendsAlertConfig } from 'products/alerts/frontend/types'

import { FunnelAlertPreviewBanner } from './AlertDefinitionFields'
import { fromLogScale, shouldUseLogScale, thresholdReferenceLines, toLogScale } from './AlertPreviewCard.utils'
import { HogQLAlertPreviewBanner } from './HogQLAlertPreview'

function allowNegativeYScale(scale: AnyScaleOptions): AnyScaleOptions {
    return { ...scale, min: undefined }
}

function AlertPreviewSparkline({
    values,
    labels,
    referenceLines,
    relative,
    renderTooltipValue,
}: {
    values: number[]
    labels?: string[]
    referenceLines: SparklineReferenceLine[]
    relative: boolean
    renderTooltipValue?: (value: number) => string
}): JSX.Element {
    return (
        <Sparkline
            type="line"
            data={values}
            labels={labels}
            maximumIndicator={false}
            referenceLines={referenceLines}
            renderTooltipValue={renderTooltipValue}
            withYScale={relative ? allowNegativeYScale : undefined}
            className="w-full h-24 flex flex-col"
        />
    )
}

export interface AlertPreviewCardProps {
    alertForm: AlertFormType
    trendsValues: number[] | null
    trendsLabels?: string[] | null
    funnelPreview: FunnelAlertPreview | null
    hogqlPreview: HogQLAlertPreview | null
    checkPreview?: TrendsAlertPreviewSeries
    // Keeps the card visible with a skeleton while data loads instead of popping in once it arrives.
    loading?: boolean
}

export function AlertPreviewCard({
    alertForm,
    trendsValues,
    trendsLabels,
    funnelPreview,
    hogqlPreview,
    checkPreview,
    loading,
}: AlertPreviewCardProps): JSX.Element {
    const config = alertForm.config
    const trendsPreview = trendsValues
        ? deriveTrendsAlertPreviewSeries(
              trendsValues,
              trendsLabels ?? undefined,
              alertForm.condition?.type ?? AlertConditionType.ABSOLUTE_VALUE,
              alertForm.threshold?.configuration?.type ?? InsightThresholdType.ABSOLUTE
          )
        : null
    const referenceLines = thresholdReferenceLines(alertForm)
    const useLogScale = Boolean(trendsPreview && shouldUseLogScale(trendsPreview.values, referenceLines))
    const previewValues = useLogScale ? trendsPreview?.values.map(toLogScale) : trendsPreview?.values
    const previewReferenceLines = useLogScale
        ? referenceLines.map((line) => ({ ...line, value: toLogScale(line.value) }))
        : referenceLines
    const checkPreviewValues = checkPreview?.values
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
    if (isUnconfiguredAbsoluteThreshold) {
        body = (
            <div className="flex h-24 items-center justify-center rounded border border-dashed border-border text-sm text-muted">
                Set less than or more than to preview this alert.
            </div>
        )
    } else if (checkPreviewValues && checkPreviewValues.length > 0) {
        body = (
            <AlertPreviewSparkline
                values={checkPreviewValues}
                labels={checkPreview.labels}
                referenceLines={referenceLines}
                relative={checkPreview.relative}
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
    } else if (isTrendsAlertConfig(config) && previewValues && previewValues.length > 0) {
        body = (
            <AlertPreviewSparkline
                values={previewValues}
                labels={trendsPreview?.labels}
                referenceLines={previewReferenceLines}
                renderTooltipValue={useLogScale ? fromLogScale : undefined}
                relative={!!trendsPreview?.relative}
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
    if (checkPreviewValues?.length) {
        lastValue = checkPreviewValues[checkPreviewValues.length - 1]
    } else if (isTrendsAlertConfig(config) && trendsPreview?.values.length) {
        lastValue = trendsPreview.values[trendsPreview.values.length - 1]
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                    <span>{checkPreview !== undefined ? 'Recent evaluations' : 'Preview'}</span>
                    <Tooltip
                        title={
                            checkPreview !== undefined
                                ? 'Values recorded by recent alert evaluations.'
                                : 'What this alert is watching right now. The dashed lines are your thresholds; points crossing them would fire.'
                        }
                        delayMs={0}
                    >
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
