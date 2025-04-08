import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { ChainedStackTraces, FingerprintCheckers } from 'lib/components/Errors/StackTraces'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { useCallback } from 'react'
import { match, P } from 'ts-pattern'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { LibIcon } from './LibIcon'

export function StacktraceDisplay(): JSX.Element {
    const {
        exceptionList,
        issue,
        hasStacktrace,
        properties,
        showFingerprint,
        showAllFrames,
        fingerprintRecords,
        propertiesLoading,
    } = useValues(errorTrackingIssueSceneLogic)

    const renderTraceHeader = useCallback(
        (id: string | undefined, type: string, value: string, checkers?: FingerprintCheckers): React.ReactNode => {
            return (
                <div>
                    <div className="flex gap-2 items-center h-7">
                        <LibIcon lib={properties?.$lib} />
                        <div className="font-bold text-lg">{type}</div>
                        {id && checkers && checkers.includesExceptionType(id) && (
                            <IconFingerprint
                                fontSize="17px"
                                color={checkers.isExceptionTypeHighlighted(id) ? 'red' : 'gray'}
                            />
                        )}
                    </div>
                    <div className="text-tertiary h-7 truncate">{value}</div>
                </div>
            )
        },
        [properties]
    )
    return (
        <div>
            {match([propertiesLoading, hasStacktrace])
                .with([true, P.any], () => (
                    <div className="space-y-2">
                        <LemonSkeleton className="w-[25%] h-5" />
                        <LemonSkeleton className="w-[50%] h-5" />
                    </div>
                ))
                .with([false, true], () => (
                    <ChainedStackTraces
                        showAllFrames={showAllFrames}
                        exceptionList={exceptionList}
                        renderTraceHeader={renderTraceHeader}
                        fingerprintRecords={showFingerprint ? fingerprintRecords : undefined}
                    />
                ))
                .with([false, false], () => (
                    <div>
                        {renderTraceHeader(undefined, issue?.name || 'Unknown', issue?.description || 'Unknown')}
                        <EmptyMessage
                            title="No stacktrace available"
                            description="Make sure sdk is setup correctly or contact support if problem persists"
                            buttonText="Check documentation"
                            buttonTo="https://posthog.com/docs/error-tracking/installation"
                        />
                    </div>
                ))
                .exhaustive()}
        </div>
    )
}
