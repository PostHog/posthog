import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { HealthIssue } from '../types'

export function HealthIssueSnoozedTag({ issue }: { issue: HealthIssue }): JSX.Element | null {
    if (!issue.snoozed_until || !dayjs(issue.snoozed_until).isAfter(dayjs())) {
        return null
    }

    return (
        <LemonTag type="muted" size="small" className="shrink-0">
            Snoozed until {dayjs(issue.snoozed_until).format('MMM D')}
        </LemonTag>
    )
}
