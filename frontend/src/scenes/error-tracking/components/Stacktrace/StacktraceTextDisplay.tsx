import { LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingException, ErrorTrackingStackFrame } from 'lib/components/Errors/types'
import { hasStacktrace } from 'lib/components/Errors/utils'
import { cn } from 'lib/utils/css-classes'
import { useEffect } from 'react'
import { match, P } from 'ts-pattern'

import { StacktraceBaseDisplayProps, StacktraceBaseExceptionHeaderProps } from './StacktraceBase'

export function StacktraceTextDisplay({
    className,
    attributes,
    renderLoading,
    renderEmpty,
    loading,
}: StacktraceBaseDisplayProps): JSX.Element {
    const { exceptionList } = attributes
    const exceptionWithStacktrace = hasStacktrace(exceptionList)
    return (
        <div className={className}>
            {match([loading, exceptionWithStacktrace])
                .with([true, P.any], () => renderLoading())
                .with([false, false], () => renderEmpty())
                .with([false, true], () =>
                    exceptionList.map((exception) => <ExceptionTextDisplay key={exception.id} exception={exception} />)
                )
                .exhaustive()}
        </div>
    )
}

export function StacktraceTextExceptionHeader({
    type,
    value,
    loading,
}: StacktraceBaseExceptionHeaderProps): JSX.Element {
    return (
        <div className={cn('font-mono')}>
            {loading ? (
                <div>
                    <LemonSkeleton className="h-2 w-1/2" />
                </div>
            ) : (
                <>
                    {type}: {value}
                </>
            )}
        </div>
    )
}

function ExceptionTextDisplay({ exception }: { exception: ErrorTrackingException }): JSX.Element {
    const { showAllFrames } = useValues(stackFrameLogic)
    return (
        <div>
            <p className="font-mono mb-0 font-bold line-clamp-1">
                {exception.type}: {exception.value}
            </p>
            {(exception.stacktrace?.frames || [])
                .filter((frame: ErrorTrackingStackFrame) => (showAllFrames ? true : frame.in_app))
                .map((frame, idx) => (
                    <StackframeTextDisplay key={idx} frame={frame} />
                ))}
        </div>
    )
}

function StackframeTextDisplay({ frame }: { frame: ErrorTrackingStackFrame }): JSX.Element {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const { loadFromRawIds } = useActions(stackFrameLogic)
    useEffect(() => {
        loadFromRawIds([frame.raw_id])
    }, [loadFromRawIds, frame.raw_id])
    return (
        <>
            <p className="font-mono indent-[1rem] whitespace-no-wrap mb-0 line-clamp-1">
                File "{frame.source}", line: {frame.line}, in: {frame.resolved_name}
            </p>
            {stackFrameRecords[frame.raw_id] && stackFrameRecords[frame.raw_id].context?.line.line && (
                <p className="font-mono indent-[2rem] whitespace-no-wrap mb-0 text-tertiary line-clamp-1">
                    {stackFrameRecords[frame.raw_id].context?.line.line}
                </p>
            )}
        </>
    )
}
