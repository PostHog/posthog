import { IconWarning } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { TodayMarkedFigure, daysAgo, staleEvidenceDate } from './todayReportPresentation'

/** Says how old the evidence behind a paragraph's figures is, when all of it is more than a week old. */
export function TodayEvidenceAge({
    marked,
    reportUpdatedAt,
    lastSeen,
}: {
    marked: TodayMarkedFigure[]
    reportUpdatedAt: string
    lastSeen: string | null
}): JSX.Element | null {
    const date = staleEvidenceDate(marked)
    // The header already shows the report's age, so the line only speaks when the figures are older than the report.
    if (!date || daysAgo(date) <= daysAgo(reportUpdatedAt)) {
        return null
    }
    return (
        <Text
            size="xs"
            variant="muted"
            render={<p />}
            className="mt-1 flex items-center gap-1"
            data-attr="today-report-evidence-age"
        >
            <IconWarning className="size-3.5 shrink-0 text-[var(--warning-foreground)]" aria-hidden />
            <span>
                Figures as of <time dateTime={date}>{dayjs(date).format('D MMM')}</time> ·{' '}
                <span className="font-medium text-[var(--foreground)]">{daysAgo(date)} days old</span>
                {lastSeen && dayjs(lastSeen).isAfter(date, 'day') && (
                    <>
                        {' · '}Last seen <time dateTime={lastSeen}>{dayjs(lastSeen).format('D MMM')}</time>
                    </>
                )}
            </span>
        </Text>
    )
}
