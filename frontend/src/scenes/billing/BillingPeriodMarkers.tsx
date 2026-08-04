import { useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import { useChartLayout } from '@posthog/quill-charts'

import { Dayjs, dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface BillingPeriodMarker {
    date: Dayjs
}

/**
 * Resolves a marker timestamp to an x pixel by interpolating between the two labels that bracket it.
 * A billing period rarely starts exactly on a bucket boundary — on week and month intervals it lands
 * between two labels — so snapping to the nearest label would misplace the marker by up to half a
 * bucket. Returns null when the timestamp falls outside the plotted range.
 */
export function resolveMarkerX(markerTs: number, labelTimestamps: number[], labelX: number[]): number | null {
    for (let i = 0; i < labelTimestamps.length - 1; i++) {
        const [from, to] = [labelTimestamps[i], labelTimestamps[i + 1]]
        if (markerTs < from || markerTs > to) {
            continue
        }
        if (to === from) {
            return labelX[i]
        }
        return labelX[i] + ((markerTs - from) / (to - from)) * (labelX[i + 1] - labelX[i])
    }
    // A single-bucket chart has no interval to interpolate across.
    if (labelTimestamps.length === 1 && markerTs === labelTimestamps[0]) {
        return labelX[0]
    }
    return null
}

// The label must not drive the chart's crosshair or tooltip, which track the wrapper's mouse events.
const stopPointerPropagation = (e: React.MouseEvent<HTMLDivElement>): void => {
    e.stopPropagation()
}

function BillingPeriodExplanation(): JSX.Element {
    return (
        <div className="p-2">
            <strong>New billing period started</strong>
            <p className="mt-2 text-xs">
                Pricing tiers reset when billing periods begin, which can cause temporary usage and spend changes:
            </p>
            <ul className="mt-1 text-xs list-disc list-inside">
                <li>Usage may drop to zero in last days of the billing period after billing limits are reached</li>
                <li>Zero spend in first days due to free tier allowance</li>
                <li>Higher daily spend in first days due to higher rates at lower volume tiers</li>
            </ul>
        </div>
    )
}

/**
 * Dashed vertical lines marking each billing period start, plus a hoverable label on the most recent
 * one. Renders as a chart overlay child, reading pixel positions off the chart's own scales.
 */
export function BillingPeriodMarkers({ markers }: { markers: BillingPeriodMarker[] }): JSX.Element | null {
    const { labels, scales, dimensions, theme } = useChartLayout()

    const positions = useMemo(() => {
        const labelTimestamps = labels.map((label) => dayjs.utc(label).valueOf())
        const labelX = labels.map((label) => scales.x(label) ?? NaN)
        return markers
            .map((marker) => resolveMarkerX(marker.date.utc().startOf('day').valueOf(), labelTimestamps, labelX))
            .filter((left): left is number => left !== null && isFinite(left))
        // eslint-disable-next-line react-hooks/exhaustive-deps -- only `scales.x` is read; `scales` itself is unused.
    }, [markers, labels, scales.x])

    if (!positions.length) {
        return null
    }

    const lineColor = theme.axisLineColor ?? theme.axisColor ?? 'currentColor'
    const labelLeft = positions[positions.length - 1]

    return (
        <>
            {positions.map((left, idx) => (
                <div
                    key={`billing-period-line-${idx}`}
                    className="BillingPeriodMarkerLine"
                    style={
                        {
                            '--billing-marker-left': `${left}px`,
                            '--billing-marker-top': `${dimensions.plotTop}px`,
                            '--billing-marker-height': `${dimensions.plotHeight}px`,
                            '--billing-marker-line-color': lineColor,
                        } as React.CSSProperties
                    }
                />
            ))}
            <div
                className="BillingMarker"
                style={
                    {
                        '--billing-marker-left': `${labelLeft}px`,
                        '--billing-marker-top': `${dimensions.plotTop}px`,
                    } as React.CSSProperties
                }
                onMouseEnter={stopPointerPropagation}
                onMouseMove={stopPointerPropagation}
            >
                <Tooltip title={<BillingPeriodExplanation />} placement="bottom">
                    <div className="BillingMarkerLabel">
                        New billing period
                        <IconInfo className="w-3 h-3" />
                    </div>
                </Tooltip>
            </div>
        </>
    )
}
