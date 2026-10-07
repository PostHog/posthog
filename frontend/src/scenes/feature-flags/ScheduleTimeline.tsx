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
const LABEL_FONT_SIZE = 9
/** Average width of one label character at the 9px size, measured in a browser. */
const LABEL_CHAR_WIDTH = 4.5
/**
 * The longest string either builder can produce. stepLabel and markerLabel tie at 27 characters, the
 * other being "3 variants (needs approval)".
 */
const WIDEST_LABEL = 'still 100% (needs approval)'
/**
 * Inside this distance from an edge, a centered label leaves the plot. Half the widest label, plus
 * headroom for a wider fallback font. Derived rather than written down, so lengthening either
 * builder's longest string carries through here on its own.
 */
const LABEL_EDGE_PAD = (WIDEST_LABEL.length * LABEL_CHAR_WIDTH) / 2 + 5
/** The width estimate runs short on labels such as "On". Two labels with no space between them read as one word. */
const LABEL_GAP = LABEL_CHAR_WIDTH
const TOP_LABEL_LANE_OFFSET = LABEL_FONT_SIZE + 1

type LabelAnchor = 'start' | 'middle' | 'end'

function describeCoveringLevel(projected: ScheduleProjectedState): string {
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
        const added = `add a condition at ${addedRolloutPercentage}% rollout`
        return occurrence.rolloutUnchanged ? `${added}, no change from the ${describeCoveringLevel(projected)}` : added
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

/**
 * `unlabelledRollout` is the level of a step whose label was dropped for overlapping an earlier one.
 * Without it such a mark is a bare dot: the drop takes away the only reading of its level, and a
 * plain step has no other reason to carry a title.
 */
function markTitle(occurrence: ScheduleOccurrence, unlabelledRollout: number | null): string {
    return [
        unlabelledRollout !== null ? `${unlabelledRollout}% rollout` : '',
        occurrence.needsApproval ? 'Needs approval' : '',
        occurrence.rolloutUnchanged
            ? `This condition sits at ${occurrence.addedRolloutPercentage}%, at or below the ${describeCoveringLevel(occurrence.projected)}`
            : '',
    ]
        .filter(Boolean)
        .join('. ')
}

function withApprovalNote(occurrence: ScheduleOccurrence, label: string): string {
    return occurrence.needsApproval ? `${label} (needs approval)` : label
}

function describeScheduledOccurrence(occurrence: ScheduleOccurrence, timezone: string): string {
    return withApprovalNote(
        occurrence,
        `${describeOccurrence(occurrence)} on ${formatOccurrenceTime(occurrence.timestamp, timezone)}`
    )
}

function stepLabel(occurrence: ScheduleOccurrence, rollout: number): string {
    return withApprovalNote(occurrence, occurrence.rolloutUnchanged ? `still ${rollout}%` : `${rollout}%`)
}

/**
 * Near an edge a label ends or starts at its mark, because the SVG clips what leaves the viewBox.
 * Both step labels and marker labels anchor through here.
 */
function labelAnchor(x: number): LabelAnchor {
    if (x > MARGIN.left + PLOT_WIDTH - LABEL_EDGE_PAD) {
        return 'end'
    }
    if (x < MARGIN.left + LABEL_EDGE_PAD) {
        return 'start'
    }
    return 'middle'
}

interface PlacedLabel {
    text: string
    y: number
    anchor: LabelAnchor
    left: number
    right: number
}

function placeLabel(x: number, y: number, text: string): PlacedLabel {
    const anchor = labelAnchor(x)
    const width = text.length * LABEL_CHAR_WIDTH
    const left = anchor === 'start' ? x : anchor === 'end' ? x - width : x - width / 2
    return { text, y, anchor, left, right: left + width }
}

function overlapsAny(label: PlacedLabel, placed: PlacedLabel[]): boolean {
    return placed.some(
        (shown) =>
            Math.abs(shown.y - label.y) < LABEL_FONT_SIZE &&
            label.left < shown.right + LABEL_GAP &&
            label.right + LABEL_GAP > shown.left
    )
}

/** Where each occurrence's marks and labels land, resolved before render so the JSX map stays pure. */
interface OccurrenceLayout {
    x: number
    /** Null when the previous time label is too close. */
    timeLabel: string | null
    /** The step mark's y. Null for a marker. */
    stepY: number | null
    /**
     * Null for a step label that would overlap an earlier label whose baseline sits within one font
     * size of its own. One font size is 9 units and the plot spends 0.9 units per rollout point, so two
     * steps less than about 10 points apart on nearby dates would otherwise stack their text.
     */
    label: PlacedLabel | null
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
    /** What the flag reaches today, the step line's starting level. See projectedRolloutPercentage. */
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
                {`Next: ${describeScheduledOccurrence(occurrence, timezone)}`}
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
    const placedLabels: PlacedLabel[] = []
    occurrences.forEach((occurrence, index) => {
        const x = xFor(times[index])
        const timeLabel = x - lastTimeLabelX >= TIME_LABEL_MIN_GAP ? relativeLabel(times[index], now) : null
        if (timeLabel) {
            lastTimeLabelX = x
        }
        let stepY: number | null = null
        let label: PlacedLabel | null
        const rollout = occurrence.projected.rolloutPercentage
        if (occurrence.operation === ScheduledChangeOperationType.AddReleaseCondition && rollout !== null) {
            stepY = yForRollout(rollout)
            const candidate = placeLabel(x, stepY - 7, stepLabel(occurrence, rollout))
            label = overlapsAny(candidate, placedLabels) ? null : candidate
        } else {
            const text = withApprovalNote(occurrence, markerLabel(occurrence))
            const lanes = [0, 1].map((lane) => placeLabel(x, MARGIN.top - 8 - lane * TOP_LABEL_LANE_OFFSET, text))
            // A marker label is the only visible text that names its change. The layout therefore
            // never drops it.
            label = lanes.find((lane) => !overlapsAny(lane, placedLabels)) ?? lanes[0]
        }
        if (label) {
            placedLabels.push(label)
        }
        layouts.push({ x, timeLabel, stepY, label })
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

    // A known level is not the same as a drawn segment. A plan whose only plottable step is its last
    // occurrence draws a labelled mark and no segment: the step has no level before it to run from,
    // and the trailing run stops at the plot edge the mark already sits on. Reading the segments here
    // would tell that reader no line is drawn because every condition is targeted, beside a mark
    // proving otherwise.
    const hasRolloutLevel = currentRolloutPercentage !== null || layouts.some((layout) => layout.stepY !== null)

    // role="img" makes the chart a single leaf node, so a screen reader never descends into the
    // marks and hears no date, level, or approval state. The label has to carry the plan itself.
    const chartLabel = `Timeline of ${occurrences.length} upcoming scheduled changes: ${occurrences
        .map((occurrence) => describeScheduledOccurrence(occurrence, timezone))
        .join(', then ')}`

    return (
        <div className="flex flex-col gap-1">
            {/* The chart scrolls horizontally rather than scale its 9-unit labels below legibility.
                The minimum width is WIDTH itself, so at the floor one viewBox unit is one pixel and
                the labels hold at 9px. A smaller floor would scale them down by the same ratio.
                A plain div with overflow takes no focus and no arrow keys, so the scroll region
                needs a focus stop of its own to be reachable without a mouse. */}
            <div
                className="overflow-x-auto"
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
                                fontSize={LABEL_FONT_SIZE}
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
                        const { x, timeLabel, stepY, label } = layouts[index]
                        const blocked = occurrence.needsApproval
                        // A browser shows only the first <title> child as the hover tooltip.
                        const title = markTitle(
                            occurrence,
                            stepY !== null && !label ? occurrence.projected.rolloutPercentage : null
                        )
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
                                {stepY !== null ? (
                                    <circle
                                        cx={x}
                                        cy={stepY}
                                        r={3.5}
                                        fill="var(--data-color-1)"
                                        stroke="var(--color-bg-surface-primary)"
                                        strokeWidth={1.5}
                                        strokeDasharray={blocked ? '2 2' : undefined}
                                    />
                                ) : (
                                    <line
                                        x1={x}
                                        x2={x}
                                        y1={MARGIN.top - 4}
                                        y2={BASELINE_Y}
                                        stroke="var(--color-border-primary)"
                                        strokeDasharray="2 3"
                                    />
                                )}
                                {label && (
                                    <text
                                        x={x}
                                        y={label.y}
                                        textAnchor={label.anchor}
                                        fontSize={LABEL_FONT_SIZE}
                                        fill="var(--color-text-secondary)"
                                    >
                                        {label.text}
                                    </text>
                                )}
                                {timeLabel && (
                                    <text
                                        x={x}
                                        y={BASELINE_Y + 15}
                                        textAnchor="middle"
                                        fontSize={LABEL_FONT_SIZE}
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
            <p className="text-xs text-muted m-0">
                {hasRolloutLevel
                    ? 'The line shows how much of your audience the flag reaches. It does not count conditions that target specific users, or conditions set to a different audience type, because their reach depends on how many match them.'
                    : 'No rollout line is shown because every condition targets specific users or a different audience type. Their reach depends on how many match them.'}
            </p>
        </div>
    )
}
