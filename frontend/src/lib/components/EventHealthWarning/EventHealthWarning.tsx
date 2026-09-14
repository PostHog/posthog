import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { EventHealthIssue, eventHealthLogic } from './eventHealthLogic'

function issueExplanation(issue: EventHealthIssue): JSX.Element {
    if (issue.status === 'stale') {
        return (
            <>
                PostHog last saw this event <b>{dayjs(issue.lastSeenAt).fromNow()}</b>. Anything that uses it matches
                nothing newer, so recent results can be incomplete.
            </>
        )
    }
    return (
        <>
            PostHog has no definition for this event. Either it was never sent, or someone deleted the definition in
            data management. If it was never sent, anything that uses it matches nothing.
        </>
    )
}

interface EventHealthWarningProps {
    event?: string | null
    /** Drop the label and keep the icon, for a row too narrow to spend 60px on a tag. */
    iconOnly?: boolean
}

/** Warns that the event something points at stopped arriving, so it quietly matches nothing new. */
export function EventHealthWarning({ event, iconOnly = false }: EventHealthWarningProps): JSX.Element | null {
    const { eventHealthIssues } = useValues(eventHealthLogic)
    const { requestEventNames } = useActions(eventHealthLogic)

    useEffect(() => {
        requestEventNames([event])
    }, [event, requestEventNames])

    const issue = event ? eventHealthIssues[event] : undefined
    if (!issue) {
        return null
    }

    const label = issue.status === 'stale' ? 'Stale' : 'Not seen'

    return (
        <Tooltip title={issueExplanation(issue)}>
            {/* pinned: autocapture/Playwright selector — this tag shipped on actions first */}
            {iconOnly ? (
                <span className="flex text-warning" aria-label={label} data-attr="action-event-health-warning">
                    <IconWarning />
                </span>
            ) : (
                <LemonTag type="warning" data-attr="action-event-health-warning">
                    {label}
                </LemonTag>
            )}
        </Tooltip>
    )
}
