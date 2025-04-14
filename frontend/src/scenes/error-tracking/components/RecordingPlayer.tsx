import { LemonSkeleton, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export function RecordingPlayer(): JSX.Element {
    const { sessionId, mightHaveRecording, issueLoading, propertiesLoading } = useValues(errorTrackingIssueSceneLogic)

    return (
        <div>
            {match([propertiesLoading, issueLoading, mightHaveRecording, sessionId])
                .with([P.any, true, P.any], () => (
                    <div>
                        <div className="h-14 flex flex-col justify-around">
                            <LemonSkeleton className="w-[25%] h-3" />
                            <LemonSkeleton className="w-[50%] h-3" />
                        </div>
                        <div className="flex justify-center items-center h-32">
                            <Spinner />
                        </div>
                    </div>
                ))
                .with([true, false, P.any], () => (
                    <div>
                        <div className="flex justify-center items-center h-32">
                            <Spinner />
                        </div>
                    </div>
                ))
                .with([false, false, true, P.string], ([, , , id]) => (
                    <SessionRecordingPlayer playerKey="error-tracking-issue" sessionRecordingId={id} noInspector />
                ))
                .with([false, false, false], () => (
                    <div>
                        <EmptyMessage
                            title="No stacktrace available"
                            description="Make sure sdk is setup correctly or contact support if problem persists"
                            buttonText="Check documentation"
                            buttonTo="https://posthog.com/docs/error-tracking/installation"
                            size="small"
                        />
                    </div>
                ))
                .otherwise(() => null)}
        </div>
    )
}
