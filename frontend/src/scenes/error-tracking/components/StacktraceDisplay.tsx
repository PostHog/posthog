import { LemonSkeleton, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { ChainedStackTraces } from 'lib/components/Errors/StackTraces'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { cancelEvent } from '../utils'

export function StacktraceDisplay({ className }: { className?: string }): JSX.Element {
    const { exceptionList, hasStacktrace, showAllFrames, fingerprintRecords, issueLoading, propertiesLoading } =
        useValues(errorTrackingIssueSceneLogic)

    return (
        <div className={className}>
            {match([propertiesLoading, issueLoading, hasStacktrace])
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
                .with([false, false, true], () => (
                    <ChainedStackTraces
                        showAllFrames={showAllFrames}
                        exceptionList={exceptionList}
                        fingerprintRecords={fingerprintRecords}
                        onFrameContextClick={(_, e) => cancelEvent(e)}
                        embedded
                    />
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
