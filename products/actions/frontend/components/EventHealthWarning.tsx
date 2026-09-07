import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { EventHealthIssue, actionEventHealthLogic } from '../logics/actionEventHealthLogic'

function issueExplanation(issue: EventHealthIssue): JSX.Element {
    if (issue.status === 'stale') {
        return (
            <>
                PostHog last saw this event <b>{dayjs(issue.lastSeenAt).fromNow()}</b>. This action matches nothing new
                until the event arrives again, so insights that use it stay empty.
            </>
        )
    }
    return (
        <>
            PostHog has no definition for this event. Either it was never sent, or someone deleted the definition in
            data management. This action matches nothing until the event arrives.
        </>
    )
}

/** Warns that the event a step points at stopped arriving, so the action quietly matches nothing. */
export function EventHealthWarning({ event }: { event?: string | null }): JSX.Element | null {
    const { eventHealthIssues } = useValues(actionEventHealthLogic)
    const { requestEventNames } = useActions(actionEventHealthLogic)

    useEffect(() => {
        requestEventNames([event])
    }, [event, requestEventNames])

    const issue = event ? eventHealthIssues[event] : undefined
    if (!issue) {
        return null
    }

    return (
        <Tooltip title={issueExplanation(issue)}>
            <LemonTag type="warning" data-attr="action-event-health-warning">
                {issue.status === 'stale' ? 'Stale' : 'Not seen'}
            </LemonTag>
        </Tooltip>
    )
}
