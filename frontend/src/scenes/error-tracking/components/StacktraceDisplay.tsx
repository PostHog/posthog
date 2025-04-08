import { LemonSkeleton, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { FingerprintRecordPartDisplay } from 'lib/components/Errors/FingerprintRecordPartDisplay'
import { ChainedStackTraces, ExceptionHeaderProps } from 'lib/components/Errors/StackTraces'
import { useCallback } from 'react'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { RuntimeIcon } from './RuntimeIcon'

export function StacktraceDisplay({ className }: { className?: string }): JSX.Element {
    const {
        exceptionList,
        issue,
        hasStacktrace,
        exceptionAttributes,
        showFingerprint,
        showAllFrames,
        fingerprintRecords,
        issueLoading,
        propertiesLoading,
    } = useValues(errorTrackingIssueSceneLogic)

    const renderExceptionHeader = useCallback(
        ({ type, value, part }: ExceptionHeaderProps): React.ReactNode => {
            return (
                <div>
                    <div className="flex gap-2 items-center h-7">
                        <RuntimeIcon runtime={exceptionAttributes?.runtime} />
                        <div className="font-bold text-lg">{type}</div>
                        {part && <FingerprintRecordPartDisplay part={part} />}
                    </div>
                    <div className="text-tertiary h-7 truncate">{value}</div>
                </div>
            )
        },
        [exceptionAttributes]
    )

    return (
        <div className={className}>
            {match([propertiesLoading, issueLoading, hasStacktrace])
                .with([true, true, P.any], () => (
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
                        {renderExceptionHeader({
                            type: issue?.name || 'Unknown',
                            value: issue?.description || 'Unknown',
                        })}
                        <div className="flex justify-center items-center h-32">
                            <Spinner />
                        </div>
                    </div>
                ))
                .with([false, P.any, true], () => (
                    <ChainedStackTraces
                        showAllFrames={showAllFrames}
                        exceptionList={exceptionList}
                        renderExceptionHeader={renderExceptionHeader}
                        fingerprintRecords={showFingerprint ? fingerprintRecords : undefined}
                    />
                ))
                .with([false, P.any, false], () => (
                    <div>
                        {renderExceptionHeader({
                            type: issue?.name || 'Unknown',
                            value: issue?.description || 'Unknown',
                        })}
                        <EmptyMessage
                            title="No stacktrace available"
                            description="Make sure sdk is setup correctly or contact support if problem persists"
                            buttonText="Check documentation"
                            buttonTo="https://posthog.com/docs/error-tracking/installation"
                            size="small"
                        />
                    </div>
                ))
                .exhaustive()}
        </div>
    )
}
