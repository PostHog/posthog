import { Dayjs, dayjs } from 'lib/dayjs'

import { ScheduledChangeOperationType } from '~/types'

import { maxRolloutPercentage, ScheduleOccurrence } from './scheduleOccurrences'

const WIDTH = 600
const HEIGHT = 140
const MARGIN = { top: 26, right: 14, bottom: 24, left: 34 }
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom
const BASELINE_Y = MARGIN.top + PLOT_HEIGHT
/** Minimum viewBox-unit gap between time labels before the later one is dropped. */
const TIME_LABEL_MIN_GAP = 40

function describeOccurrence(occurrence: ScheduleOccurrence): string {
    const { payload } = occurrence.schedule
    if (payload.operation === ScheduledChangeOperationType.UpdateStatus) {
        return occurrence.projected.active ? 'enabled' : 'disabled'
    }
    if (payload.operation === ScheduledChangeOperationType.AddReleaseCondition) {
        // Describe the condition this change adds, not the flag's projected max rollout: the change
        // appends a condition set, so an existing higher one would otherwise be misreported here.
        const added = maxRolloutPercentage(payload.value.groups)
        return added !== null ? `add a condition at ${added}% rollout` : 'add a condition'
    }
    return `${occurrence.projected.variantCount} variant${occurrence.projected.variantCount === 1 ? '' : 's'}`
}

function markerLabel(occurrence: ScheduleOccurrence): string {
    if (occurrence.operation === ScheduledChangeOperationType.UpdateStatus) {
        return occurrence.projected.active ? 'On' : 'Off'
    }
    return `${occurrence.projected.variantCount} variant${occurrence.projected.variantCount === 1 ? '' : 's'}`
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
 * Compact projection of upcoming scheduled changes: rollout percentage as a step line over time,
 * with status flips and variant updates as labeled markers on the same time axis.
 */
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

    // Step-line segments, one per occurrence so approval-blocked steps can render dashed.
    let previousX = MARGIN.left
    let previousRollout = currentRolloutPercentage
    const stepSegments: { path: string; blocked: boolean }[] = []
    occurrences.forEach((occurrence, index) => {
        const rollout = occurrence.projected.rolloutPercentage
        if (rollout === null) {
            return
        }
        const x = xFor(times[index])
        const path =
            previousRollout === null
                ? `M ${x} ${yForRollout(rollout)}`
                : `M ${previousX} ${yForRollout(previousRollout)} H ${x} V ${yForRollout(rollout)}`
        stepSegments.push({ path, blocked: occurrence.needsApproval })
        previousX = x
        previousRollout = rollout
    })
    if (previousRollout !== null && previousX < MARGIN.left + PLOT_WIDTH) {
        stepSegments.push({
            path: `M ${previousX} ${yForRollout(previousRollout)} H ${MARGIN.left + PLOT_WIDTH}`,
            blocked: false,
        })
    }

    let lastTimeLabelX = -Infinity

    return (
        <div className="flex flex-col gap-1" data-attr="feature-flag-schedule-timeline">
            <svg
                viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                className="w-full max-w-3xl"
                role="img"
                aria-label="Timeline of upcoming scheduled changes"
            >
                {[0, 50, 100].map((rollout) => (
                    <g key={rollout}>
                        <line
                            x1={MARGIN.left}
                            x2={MARGIN.left + PLOT_WIDTH}
                            y1={yForRollout(rollout)}
                            y2={yForRollout(rollout)}
                            stroke="var(--color-border)"
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
                    const x = xFor(times[index])
                    const blocked = occurrence.needsApproval
                    const isRolloutStep = occurrence.operation === ScheduledChangeOperationType.AddReleaseCondition
                    const rollout = occurrence.projected.rolloutPercentage
                    const timeLabel = x - lastTimeLabelX >= TIME_LABEL_MIN_GAP ? relativeLabel(times[index], now) : null
                    if (timeLabel) {
                        lastTimeLabelX = x
                    }
                    return (
                        <g key={`${occurrence.schedule.id}-${occurrence.timestamp}`} opacity={blocked ? 0.5 : 1}>
                            {blocked && <title>Needs approval</title>}
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
                                        textAnchor="middle"
                                        fontSize={9}
                                        fill="var(--color-text-secondary)"
                                    >
                                        {rollout}%
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
                                        y={MARGIN.top - 8}
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
