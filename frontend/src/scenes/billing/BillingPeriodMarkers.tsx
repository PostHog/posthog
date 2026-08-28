import { useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import { useChartLayout } from '@posthog/quill-charts'

import { Dayjs, dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface BillingPeriodMarker {
    date: Dayjs
}

/** Gap between the label and the top of the plot, so it clears the topmost y-axis tick. */
const LABEL_GAP = 4

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
        // Guards the division below: chart date labels are distinct in practice, but two equal
        // adjacent timestamps would otherwise divide by zero.
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
 * Renders as a chart overlay child, reading pixel positions off the chart's own scales.
 *
 * Not built on quill's `ReferenceLine`: its vertical variant resolves x through `scales.x(label)`, so
 * it can only sit exactly on a label, and a billing period routinely starts mid-bucket on week and
 * month intervals. Its label is also a plain string, not a node, so it can't carry the explanation
 * tooltip. Teaching `ReferenceLine` to take an interpolated x would let this collapse into it.
 */
export function BillingPeriodMarkers({ markers }: { markers: BillingPeriodMarker[] }): JSX.Element | null {
    const { labels, scales, dimensions, theme } = useChartLayout()

    const labelTimestamps = useMemo(() => labels.map((label) => dayjs.utc(label).valueOf()), [labels])

    const positions = useMemo(() => {
        if (!markers.length) {
            return []
        }
        const labelX = labels.map((label) => scales.x(label) ?? NaN)
        return markers
            .map((marker) => resolveMarkerX(marker.date.utc().startOf('day').valueOf(), labelTimestamps, labelX))
            .filter((left): left is number => left !== null && isFinite(left))
        // eslint-disable-next-line react-hooks/exhaustive-deps -- only `scales.x` is read; `scales` itself is unused.
    }, [markers, labels, labelTimestamps, scales.x])

    if (!positions.length) {
        return null
    }

    const lineColor = theme.axisLineColor
    const labelLeft = Math.max(...positions)

    // Positions and the theme's line color resolve at runtime from the chart's scales, so they stay
    // inline — everything static is a utility class.
    return (
        <>
            {positions.map((left, idx) => (
                <div
                    key={`billing-period-line-${idx}`}
                    data-attr="billing-period-marker-line"
                    className="absolute -translate-x-1/2 border-l-2 border-dashed"
                    style={{
                        left,
                        top: dimensions.plotTop,
                        height: dimensions.plotHeight,
                        borderLeftColor: lineColor,
                    }}
                />
            ))}
            {/* Anchored just above the plot: that keeps it clear of the data and of the topmost y-axis
                tick, and puts the cursor outside the plot area while hovering it, which is what makes
                the chart drop its own tooltip instead of showing two at once. */}
            <div
                data-attr="billing-period-marker-label"
                className="absolute -translate-x-1/2 -translate-y-full pointer-events-auto cursor-default"
                style={{ left: labelLeft, top: dimensions.plotTop - LABEL_GAP }}
            >
                <Tooltip title={<BillingPeriodExplanation />} placement="bottom">
                    <div className="flex items-center gap-1 px-2 py-1 text-xs font-normal whitespace-nowrap rounded-sm border border-primary bg-surface-primary text-secondary">
                        New billing period
                        <IconInfo className="w-3 h-3" />
                    </div>
                </Tooltip>
            </div>
        </>
    )
}
