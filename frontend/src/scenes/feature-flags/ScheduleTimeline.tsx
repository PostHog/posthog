import { Dayjs, dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { ScheduledChangeOperationType } from '~/types'

import { ScheduleOccurrence, ScheduleProjectedState } from './scheduleOccurrences'

const WIDTH = 600
const HEIGHT = 140
const MARGIN = { top: 26, right: 14, bottom: 24, left: 34 }
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom
const BASELINE_Y = MARGIN.top + PLOT_HEIGHT
/** Minimum viewBox-unit gap between time-axis labels before the later one is dropped. */
const TIME_LABEL_MIN_GAP = 40
/** Minimum viewBox-unit gap between top labels before the later one moves to the second lane. */
const TOP_LABEL_MIN_GAP = 40
/** How far the second lane sits above the first. Tuned against the 9px label size. */
const TOP_LABEL_LANE_OFFSET = 10
/**
 * Half the widest step label at the 9px size, which measures about 120 viewBox units, plus headroom
 * for a wider fallback font. Inside this distance from an edge, a centered label leaves the plot.
 */
const STEP_LABEL_EDGE_PAD = 65

/**
 * Names the level an added condition sits under. A disabled flag serves nobody whatever its rollout
 * says, so the wording follows the projected status rather than claiming an audience either way.
 */
function coveringLevel(projected: ScheduleProjectedState): string {
    return projected.active
        ? `${projected.rolloutPercentage}% the flag already serves`
        : `${projected.rolloutPercentage}% set on this disabled flag`
}

function describeOccurrence(occurrence: ScheduleOccurrence): string {
    const { operation, projected, addedRolloutPercentage } = occurrence
    if (operation === ScheduledChangeOperationType.UpdateStatus) {
        return projected.active ? 'enabled' : 'disabled'
    }
    if (operation === ScheduledChangeOperationType.AddReleaseCondition) {
        if (addedRolloutPercentage === null) {
            return 'add a condition'
        }
        // Describe the condition this change adds, not the flag's projected max rollout: the change
        // appends a condition set, so an existing higher one would otherwise be misreported here.
        // Say when that existing one holds the level, or the plan reads as a ramp that does not ramp.
        return occurrence.rolloutUnchanged
            ? `add a condition at ${addedRolloutPercentage}% rollout, no change from the ${coveringLevel(projected)}`
            : `add a condition at ${addedRolloutPercentage}% rollout`
    }
    return `switch to ${pluralize(occurrence.projected.variantCount ?? 0, 'variant')}`
}

function markerLabel(occurrence: ScheduleOccurrence): string {
    if (occurrence.operation === ScheduledChangeOperationType.UpdateStatus) {
        return occurrence.projected.active ? 'On' : 'Off'
    }
    // A condition change reaches this label only when its projected rollout is unknown, which the
    // step line cannot plot. Without this branch it borrows the variant wording and reads "0 variants".
    if (occurrence.operation === ScheduledChangeOperationType.AddReleaseCondition) {
        return 'Condition'
    }
    return pluralize(occurrence.projected.variantCount ?? 0, 'variant')
}

function formatOccurrenceTime(timestamp: string, timezone: string): string {
    const at = dayjs(timestamp).tz(timezone)
    const format = at.year() === dayjs().tz(timezone).year() ? 'MMM D, h:mm A' : 'MMM D, YYYY h:mm A'
    return at.format(format)
}

function relativeLabel(at: Dayjs, now: Dayjs): string {
    const minutes = at.diff(now, 'minute')
    if (minutes <= 0) {
        return 'now'
    }
    if (minutes < 60) {
        return `in ${minutes}m`
    }
    const hours = at.diff(now, 'hour')
    if (hours < 48) {
        return `in ${hours}h`
    }
    return `in ${at.diff(now, 'day')}d`
}

function yForRollout(rollout: number): number {
    return MARGIN.top + ((100 - rollout) * PLOT_HEIGHT) / 100
}

/** Hover text for a mark: why it waits on approval, why its level holds, or both. */
function markTitle(occurrence: ScheduleOccurrence): string {
    return [
        occurrence.needsApproval ? 'Needs approval' : '',
        occurrence.rolloutUnchanged
            ? `This condition sits at ${occurrence.addedRolloutPercentage}%, at or below the ${coveringLevel(occurrence.projected)}`
            : '',
    ]
        .filter(Boolean)
        .join('. ')
}

/** Label above a step mark. Says when the level holds, or a flat line reads as a broken chart. */
function stepLabel(occurrence: ScheduleOccurrence, rollout: number): string {
    const level = occurrence.rolloutUnchanged ? `still ${rollout}%` : `${rollout}%`
    return occurrence.needsApproval ? `${level} (needs approval)` : level
}

/** Near an edge a label ends or starts at its mark, because the SVG clips what leaves the viewBox. */
function stepLabelAnchor(x: number): 'start' | 'middle' | 'end' {
    if (x > MARGIN.left + PLOT_WIDTH - STEP_LABEL_EDGE_PAD) {
        return 'end'
    }
    if (x < MARGIN.left + STEP_LABEL_EDGE_PAD) {
        return 'start'
    }
    return 'middle'
}

/** Where each occurrence's marks and labels land, resolved before render so the JSX map stays pure. */
interface OccurrenceLayout {
    x: number
    /** Null when the previous time label is too close. */
    timeLabel: string | null
    /** Alternates between two heights when top-lane markers land near the same x. */
    topLabelY: number
}

/**
 * Compact projection of upcoming scheduled changes: rollout percentage as a step line over time,
 * with status flips and variant updates as labeled markers on the same time axis.
 */
// Deliberately not memoized: the body reads the wall clock (`now` below) to place marks and write
// the relative time labels, so a shallow prop compare would freeze both until the occurrence list
// changes identity. Memoize once `now` arrives as a prop.
export function ScheduleTimeline({
    occurrences,
    currentRolloutPercentage,
    timezone,
}: {
    occurrences: ScheduleOccurrence[]
    /** The flag's max rollout across condition sets today, the step line's starting level. */
    currentRolloutPercentage: number | null
    timezone: string
}): JSX.Element | null {
    if (occurrences.length === 0) {
        return null
    }

    if (occurrences.length === 1) {
        const occurrence = occurrences[0]
        return (
            <div className="text-sm text-muted" data-attr="feature-flag-schedule-timeline">
                Next: {describeOccurrence(occurrence)} on {formatOccurrenceTime(occurrence.timestamp, timezone)}
                {occurrence.needsApproval ? ' (needs approval)' : ''}
            </div>
        )
    }

    const now = dayjs()
    const times = occurrences.map((occurrence) => dayjs(occurrence.timestamp))
    const spanMs = Math.max(times[times.length - 1].valueOf() - now.valueOf(), 1)
    const xFor = (at: Dayjs): number => {
        const fraction = Math.min(Math.max((at.valueOf() - now.valueOf()) / spanMs, 0), 1)
        return MARGIN.left + fraction * PLOT_WIDTH
    }

    const layouts: OccurrenceLayout[] = []
    let lastTimeLabelX = -Infinity
    let lastTopLabelX = -Infinity
    let topLabelLane = 0
    occurrences.forEach((occurrence, index) => {
        const x = xFor(times[index])
        const timeLabel = x - lastTimeLabelX >= TIME_LABEL_MIN_GAP ? relativeLabel(times[index], now) : null
        if (timeLabel) {
            lastTimeLabelX = x
        }
        let topLabelY = MARGIN.top - 8
        const onStepLine =
            occurrence.operation === ScheduledChangeOperationType.AddReleaseCondition &&
            occurrence.projected.rolloutPercentage !== null
        if (!onStepLine) {
            // Two lanes clear the common case of a pair landing together. Three or more markers
            // inside one gap still overlap, because the lane alternates rather than tracks every
            // occupied slot. The occurrence cap keeps that rare.
            topLabelLane = x - lastTopLabelX < TOP_LABEL_MIN_GAP ? 1 - topLabelLane : 0
            lastTopLabelX = x
            topLabelY -= topLabelLane * TOP_LABEL_LANE_OFFSET
        }
        layouts.push({ x, timeLabel, topLabelY })
    })

    // Step-line segments, split so an approval-blocked step dashes its jump and not its run.
    let previousX = MARGIN.left
    let previousRollout = currentRolloutPercentage
    const stepSegments: { path: string; blocked: boolean }[] = []
    occurrences.forEach((occurrence, index) => {
        const rollout = occurrence.projected.rolloutPercentage
        if (rollout === null) {
            return
        }
        const x = layouts[index].x
        const y = yForRollout(rollout)
        // A first occurrence with no level before it has nothing to draw yet, and the next
        // occurrence starts its run from here.
        if (previousRollout !== null) {
            const previousY = yForRollout(previousRollout)
            // The horizontal run holds the level the flag serves until this change fires, which is
            // certain whatever a reviewer decides. Only the jump to the new level waits on approval.
            stepSegments.push({ path: `M ${previousX} ${previousY} H ${x}`, blocked: false })
            if (previousY !== y) {
                stepSegments.push({ path: `M ${x} ${previousY} V ${y}`, blocked: occurrence.needsApproval })
            }
        }
        previousX = x
        previousRollout = rollout
    })
    if (previousRollout !== null && previousX < MARGIN.left + PLOT_WIDTH) {
        stepSegments.push({
            path: `M ${previousX} ${yForRollout(previousRollout)} H ${MARGIN.left + PLOT_WIDTH}`,
            blocked: false,
        })
    }

    // role="img" makes the chart a single leaf node, so a screen reader never descends into the
    // marks and hears no date, level, or approval state. The label has to carry the plan itself.
    const chartLabel = `Timeline of ${occurrences.length} upcoming scheduled changes: ${occurrences
        .map(
            (occurrence) =>
                `${describeOccurrence(occurrence)} on ${formatOccurrenceTime(occurrence.timestamp, timezone)}${
                    occurrence.needsApproval ? ' (needs approval)' : ''
                }`
        )
        .join(', then ')}`

    return (
        // The chart scrolls horizontally rather than scale its 9-unit labels below legibility. The
        // minimum width is WIDTH itself, so at the floor one viewBox unit is one pixel and the
        // labels hold at 9px. A smaller floor would scale them down by the same ratio.
        // A plain div with overflow takes no focus and no arrow keys, so the scroll region needs a
        // focus stop of its own to be reachable without a mouse.
        <div
            className="flex flex-col gap-1 overflow-x-auto"
            tabIndex={0}
            role="group"
            aria-label="Scrollable schedule timeline"
            data-attr="feature-flag-schedule-timeline"
        >
            <svg
                viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                className="w-full max-w-3xl"
                style={{ minWidth: WIDTH }}
                role="img"
                aria-label={chartLabel}
            >
                {[0, 50, 100].map((rollout) => (
                    <g key={rollout}>
                        <line
                            x1={MARGIN.left}
                            x2={MARGIN.left + PLOT_WIDTH}
                            y1={yForRollout(rollout)}
                            y2={yForRollout(rollout)}
                            stroke="var(--color-border-primary)"
                            strokeWidth={rollout === 0 ? 1 : 0.5}
                        />
                        <text
                            x={MARGIN.left - 4}
                            y={yForRollout(rollout) + 3}
                            textAnchor="end"
                            fontSize={9}
                            fill="var(--color-text-secondary)"
                        >
                            {rollout}%
                        </text>
                    </g>
                ))}

                {stepSegments.map((segment, index) => (
                    <path
                        key={index}
                        d={segment.path}
                        fill="none"
                        stroke="var(--data-color-1)"
                        strokeWidth={2}
                        strokeDasharray={segment.blocked ? '4 3' : undefined}
                        opacity={segment.blocked ? 0.5 : 1}
                    />
                ))}

                {occurrences.map((occurrence, index) => {
                    const { x, timeLabel, topLabelY } = layouts[index]
                    const blocked = occurrence.needsApproval
                    const isRolloutStep = occurrence.operation === ScheduledChangeOperationType.AddReleaseCondition
                    const rollout = occurrence.projected.rolloutPercentage
                    // One <title> per mark: a second one is never read out.
                    const title = markTitle(occurrence)
                    return (
                        <g key={`${occurrence.schedule.id}-${occurrence.timestamp}`} opacity={blocked ? 0.5 : 1}>
                            {title && <title>{title}</title>}
                            <line
                                x1={x}
                                x2={x}
                                y1={BASELINE_Y}
                                y2={BASELINE_Y + 4}
                                stroke="var(--color-border-primary)"
                            />
                            {isRolloutStep && rollout !== null ? (
                                <>
                                    <circle
                                        cx={x}
                                        cy={yForRollout(rollout)}
                                        r={3.5}
                                        fill="var(--data-color-1)"
                                        stroke="var(--color-bg-surface-primary)"
                                        strokeWidth={1.5}
                                        strokeDasharray={blocked ? '2 2' : undefined}
                                    />
                                    <text
                                        x={x}
                                        y={yForRollout(rollout) - 7}
                                        textAnchor={stepLabelAnchor(x)}
                                        fontSize={9}
                                        fill="var(--color-text-secondary)"
                                    >
                                        {stepLabel(occurrence, rollout)}
                                    </text>
                                </>
                            ) : (
                                <>
                                    <line
                                        x1={x}
                                        x2={x}
                                        y1={MARGIN.top - 4}
                                        y2={BASELINE_Y}
                                        stroke="var(--color-border-primary)"
                                        strokeDasharray="2 3"
                                    />
                                    <text
                                        x={x}
                                        y={topLabelY}
                                        textAnchor="middle"
                                        fontSize={9}
                                        fill="var(--color-text-secondary)"
                                    >
                                        {markerLabel(occurrence)}
                                        {blocked ? ' (needs approval)' : ''}
                                    </text>
                                </>
                            )}
                            {timeLabel && (
                                <text
                                    x={x}
                                    y={BASELINE_Y + 15}
                                    textAnchor="middle"
                                    fontSize={9}
                                    fill="var(--color-text-secondary)"
                                >
                                    {timeLabel}
                                </text>
                            )}
                        </g>
                    )
                })}
            </svg>
        </div>
    )
}
