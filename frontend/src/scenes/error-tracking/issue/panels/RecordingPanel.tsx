import { useValues } from 'kea'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

import { ErrorTrackingIssueEventsPanel } from '../Events'

const Content = (): JSX.Element => {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)

    return (
        <SessionRecordingPlayer
            playerKey="issue"
            sessionRecordingId={issueProperties['$session_id']}
            noMeta
            noBorder
            autoPlay
            noInspector
            matchingEventsMatchType={{
                matchType: 'name',
                eventNames: ['$exception'],
            }}
        />
    )
}

const EmptyState = (): JSX.Element => {
    return <div>Empty State</div>
}

export default {
    key: 'recording',
    Content,
    Header: 'Recording',
    EmptyState,
    hasContent: ({ issueProperties }) =>
        issueProperties['$session_id'] && issueProperties['$recording_status'] === 'active',
    className: 'p-0',
} as ErrorTrackingIssueEventsPanel
