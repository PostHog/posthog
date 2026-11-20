import { Text, cn } from '@posthog/quill'

import { MINUTES_PER_DAY } from 'products/alerts/frontend/logic/scheduleRestrictionValidation'

import { QuietHoursDayTimelineProps } from './QuietHoursDayTimeline'
import {
    buildDayTimelineSegments,
    formatMinuteLabel,
    HOUR_START_MINUTES,
    timelineAriaPieces,
} from './quietHoursDayTimelineSegments'

const ALLOWED_FILL = 'bg-success-foreground'
const QUIET_FILL = 'bg-muted'

/** Single-row 24h bar: allowed (run) vs blocked (quiet) in project-local wall time. */
export function QuillQuietHoursDayTimeline({ windows }: QuietHoursDayTimelineProps): JSX.Element | null {
    const segments = buildDayTimelineSegments(windows)
    if (!segments?.length) {
        return null
    }

    const ariaPieces = timelineAriaPieces(segments)

    return (
        <div className="flex flex-col gap-1.5" data-attr="alertForm-quiet-day-timeline">
            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                One local day (project timezone)
            </Text>
            <div
                className="flex h-4 w-full overflow-hidden rounded-sm border border-border"
                role="img"
                aria-label={`Quiet hours and run times throughout the day: ${ariaPieces.join('; ')}.`}
            >
                {segments.map((s) => (
                    <div
                        key={`${s.kind}-${s.from}-${s.to}`}
                        title={`${formatMinuteLabel(s.from)}–${formatMinuteLabel(s.to)} · ${
                            s.kind === 'allowed' ? 'Alert can run' : 'Quiet hours'
                        }`}
                        className={cn('min-w-px shrink-0', s.kind === 'allowed' ? ALLOWED_FILL : QUIET_FILL)}
                        style={{ width: `${((s.to - s.from) / MINUTES_PER_DAY) * 100}%` }}
                    />
                ))}
            </div>
            <div className="grid w-full grid-cols-24 text-xxs leading-none text-muted-foreground tabular-nums">
                {HOUR_START_MINUTES.map((m, hour) => (
                    <span
                        key={m}
                        className={cn(
                            'block min-w-0 text-center',
                            hour % 2 === 1 && 'max-sm:invisible max-sm:select-none'
                        )}
                    >
                        {formatMinuteLabel(m)}
                    </span>
                ))}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <Text size="xs" variant="muted" render={<span className="m-0 flex items-center gap-1" />}>
                    <span className={cn('inline-block size-2.5 shrink-0 rounded-xs', ALLOWED_FILL)} aria-hidden />
                    Runs allowed
                </Text>
                <Text size="xs" variant="muted" render={<span className="m-0 flex items-center gap-1" />}>
                    <span className={cn('inline-block size-2.5 shrink-0 rounded-xs', QUIET_FILL)} aria-hidden />
                    Quiet hours
                </Text>
            </div>
        </div>
    )
}
