import { blockedAndAllowedMinuteIntervalsForQuietHours, MINUTES_PER_DAY } from '../scheduleRestrictionValidation'
import type { BlockedWindow } from '../types'

type TimelineSegment = { kind: 'blocked' | 'allowed'; from: number; to: number }

function buildDayTimelineSegments(windows: BlockedWindow[]): TimelineSegment[] | null {
    const both = blockedAndAllowedMinuteIntervalsForQuietHours(windows)
    if (both === null) {
        return null
    }
    const { blocked: merged, allowed } = both
    return [
        ...merged.map(([from, to]) => ({ kind: 'blocked' as const, from, to })),
        ...allowed.map(([from, to]) => ({ kind: 'allowed' as const, from, to })),
    ].sort((a, b) => a.from - b.from || a.to - b.to)
}

function formatMinuteLabel(m: number): string {
    if (m <= 0 || m >= MINUTES_PER_DAY) {
        return '12a'
    }
    const h = Math.floor(m / 60)
    const isPm = h >= 12
    const hour12 = h % 12 === 0 ? 12 : h % 12
    return `${hour12}${isPm ? 'p' : 'a'}`
}

/** Hour starts 12am … 11pm (24 columns under the bar). */
const HOUR_START_MINUTES = Array.from({ length: 24 }, (_, h) => h * 60)

export interface QuietHoursDayTimelineProps {
    windows: BlockedWindow[]
}

/** Single-row 24h bar: allowed (run) vs blocked (quiet) in project-local wall time. */
export function QuietHoursDayTimeline({ windows }: QuietHoursDayTimelineProps): JSX.Element | null {
    const segments = buildDayTimelineSegments(windows)
    if (!segments?.length) {
        return null
    }

    const ariaPieces = segments.map((s) => {
        const kind = s.kind === 'allowed' ? 'alert may run' : 'quiet hours'
        return `${formatMinuteLabel(s.from)}–${formatMinuteLabel(s.to)} ${kind}`
    })

    return (
        <div className="space-y-1.5" data-attr="alertForm-quiet-day-timeline">
            <div className="text-secondary text-xs">One local day (project timezone)</div>
            <div
                className="flex h-4 w-full overflow-hidden rounded border border-primary"
                role="img"
                aria-label={`Quiet hours and run times throughout the day: ${ariaPieces.join('; ')}.`}
            >
                {segments.map((s) => (
                    <div
                        key={`${s.kind}-${s.from}-${s.to}`}
                        title={`${formatMinuteLabel(s.from)}–${formatMinuteLabel(s.to)} · ${
                            s.kind === 'allowed' ? 'Alert can run' : 'Quiet hours'
                        }`}
                        className={
                            s.kind === 'allowed'
                                ? 'min-w-px shrink-0 bg-success dark:bg-success-light'
                                : 'min-w-px shrink-0 bg-fill-secondary'
                        }
                        style={{ width: `${((s.to - s.from) / MINUTES_PER_DAY) * 100}%` }}
                    />
                ))}
            </div>
            <div className="grid w-full grid-cols-[repeat(24,minmax(0,1fr))] text-secondary text-[8px] leading-none tabular-nums sm:text-[9px]">
                {HOUR_START_MINUTES.map((m, hour) => (
                    <span
                        key={m}
                        className={`block min-w-0 text-center ${hour % 2 === 1 ? 'max-sm:invisible max-sm:select-none' : ''}`}
                    >
                        {formatMinuteLabel(m)}
                    </span>
                ))}
            </div>
            <p className="text-secondary text-xs m-0">
                <span className="inline-block size-2.5 shrink-0 rounded-sm bg-success dark:bg-success-light mr-1 align-middle" />{' '}
                Runs allowed
                <span className="mx-2 text-border">·</span>
                <span className="inline-block size-2.5 shrink-0 rounded-sm bg-fill-secondary mr-1 align-middle" /> Quiet
                hours
            </p>
        </div>
    )
}
