import { IconInfo } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Sparkline, SparklineReferenceLine } from 'lib/components/Sparkline'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { FunnelAlertPreview } from 'products/alerts/frontend/logic/funnelAlertPreview'
import { HogQLAlertPreview } from 'products/alerts/frontend/logic/hogqlAlertPreview'
import { isFunnelsAlertConfig, isHogQLAlertConfig, isTrendsAlertConfig } from 'products/alerts/frontend/types'

import { FunnelAlertPreviewBanner } from './AlertDefinitionFields'
import { HogQLAlertPreviewBanner } from './HogQLAlertPreview'

export interface AlertPreviewCardProps {
    alertForm: AlertFormType
    /** Trends: the monitored series' values, oldest→newest. Null when not a trends alert or no data. */
    trendsValues: number[] | null
    /** Trends: the labels for `trendsValues` (dates). */
    trendsLabels?: string[] | null
    funnelPreview: FunnelAlertPreview | null
    hogqlPreview: HogQLAlertPreview | null
}

/** Threshold bounds as dashed reference lines for the Sparkline. Returns lower+upper when both are
 *  set, or just one. Scales funnel/percentage thresholds the same way the threshold inputs do. */
function thresholdReferenceLines(alertForm: AlertFormType): SparklineReferenceLine[] {
    const config = alertForm.threshold?.configuration
    if (!config) {
        return []
    }
    const isPercentage = config.type === InsightThresholdType.PERCENTAGE
    const lines: SparklineReferenceLine[] = []
    const lo = config.bounds?.lower
    const hi = config.bounds?.upper
    if (lo != null && !Number.isNaN(lo)) {
        lines.push({
            value: isPercentage ? (lo as number) * 100 : (lo as number),
            color: 'danger',
            label: `below ${humanFriendlyNumber(isPercentage ? (lo as number) * 100 : (lo as number))}`,
        })
    }
    if (hi != null && !Number.isNaN(hi)) {
        lines.push({
            value: isPercentage ? (hi as number) * 100 : (hi as number),
            color: 'danger',
            label: `above ${humanFriendlyNumber(isPercentage ? (hi as number) * 100 : (hi as number))}`,
        })
    }
    return lines
}

/** A persistent, at-a-glance preview of what the alert is watching. For trends this is a sparkline
 *  of the monitored series with the current threshold drawn as dashed lines, so the cause→effect of
 *  moving a threshold is immediate. For funnels and SQL it reuses the existing preview banners. */
export function AlertPreviewCard({
    alertForm,
    trendsValues,
    trendsLabels,
    funnelPreview,
    hogqlPreview,
}: AlertPreviewCardProps): JSX.Element {
    const config = alertForm.config
    const isDetector = !!alertForm.detector_config

    let body: JSX.Element | null = null
    if (isTrendsAlertConfig(config) && trendsValues && trendsValues.length > 0) {
        const referenceLines = isDetector ? [] : thresholdReferenceLines(alertForm)
        body = (
            <Sparkline
                type="line"
                data={trendsValues}
                labels={trendsLabels ?? undefined}
                maximumIndicator={false}
                referenceLines={referenceLines}
                className="w-full"
            />
        )
    } else if (isFunnelsAlertConfig(config) && funnelPreview) {
        body = <FunnelAlertPreviewBanner preview={funnelPreview} />
    } else if (isHogQLAlertConfig(config) && hogqlPreview) {
        body = <HogQLAlertPreviewBanner preview={hogqlPreview} conditionType={alertForm.condition?.type} />
    }

    if (!body) {
        return <></>
    }

    const lastValue =
        isTrendsAlertConfig(config) && trendsValues && trendsValues.length > 0
            ? trendsValues[trendsValues.length - 1]
            : null

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-sm font-medium">
                    <span>Preview</span>
                    <Tooltip
                        title="What this alert is watching right now. The dashed lines are your thresholds; points crossing them would fire."
                        delayMs={0}
                    >
                        <IconInfo className="text-muted size-3.5" />
                    </Tooltip>
                </div>
                {lastValue != null ? (
                    <LemonTag type="default" className="m-0">
                        Latest: <strong className="ml-1">{humanFriendlyNumber(lastValue)}</strong>
                    </LemonTag>
                ) : null}
            </div>
            {body}
        </div>
    )
}
