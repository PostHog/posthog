import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

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
            data management. Anything that uses it matches nothing new.
        </>
    )
}

/** Warns that the event something points at stopped arriving, so it quietly matches nothing new. */
export function EventHealthWarning({ event }: { event?: string | null }): JSX.Element | null {
    const { eventHealthIssues } = useValues(eventHealthLogic)
    const { requestEventNames } = useActions(eventHealthLogic)

    useEffect(() => {
        requestEventNames([event])
    }, [event, requestEventNames])

    const issue = event ? eventHealthIssues[event] : undefined
    if (!issue) {
        return null
    }

    return (
        <Tooltip title={issueExplanation(issue)}>
            {/* pinned: autocapture/Playwright selector — this tag shipped on actions first */}
            <LemonTag type="warning" data-attr="action-event-health-warning">
                {issue.status === 'stale' ? 'Stale' : 'Not seen'}
            </LemonTag>
        </Tooltip>
    )
}
