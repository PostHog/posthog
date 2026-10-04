import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import type { SignalReport } from 'products/signals/frontend/inbox/types'

import { daysAgo } from './todayFigureSources'
import { shortDate } from './todayProse'
import { todayReportLogic } from './todayReportLogic'

export function TodayEvidenceAge({ report }: { report: Pick<SignalReport, 'id' | 'updated_at'> }): JSX.Element | null {
    const { lastSeen, staleFiguresDate: date } = useValues(todayReportLogic({ reportId: report.id }))
    if (!date || daysAgo(date) <= daysAgo(report.updated_at)) {
        return null
    }
    const seenSince = lastSeen && dayjs(lastSeen).isAfter(date, 'day') ? lastSeen : null
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
                Figures as of <time dateTime={date}>{shortDate(date)}</time> ·{' '}
                <span className="font-medium text-foreground">{daysAgo(date)} days old</span>
                {seenSince && (
                    <>
                        {' · '}Last seen <time dateTime={seenSince}>{shortDate(seenSince)}</time>
                    </>
                )}
            </span>
        </Text>
    )
}
