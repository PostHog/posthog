import { useMemo } from 'react'
import { match } from 'ts-pattern'

import { ErrorTrackingException, ErrorTrackingStackFrame } from '../types'
import { KnownException, KnownExceptionRegistry } from './known-exceptions'

type StackTraceRenderer = (
    frames: ErrorTrackingStackFrame[],
    exception: ErrorTrackingException,
    knownException?: KnownException
) => React.ReactNode

export type ExceptionRendererProps = {
    className?: string
    exception: ErrorTrackingException
    frameFilter?: (frame: ErrorTrackingStackFrame) => boolean
    renderExceptionHeader: (exception: ErrorTrackingException) => React.ReactNode

    renderUndefinedTrace: (exception: ErrorTrackingException, knownException?: KnownException) => React.ReactNode
    renderResolvedTrace: StackTraceRenderer
    renderFilteredTrace: (
        allFrames: ErrorTrackingStackFrame[],
        exception: ErrorTrackingException,
        knownException?: KnownException
    ) => React.ReactNode
}

export function ExceptionRenderer({
    className,
    exception,
    frameFilter,
    renderExceptionHeader,
    renderUndefinedTrace,
    renderResolvedTrace,
    renderFilteredTrace,
}: ExceptionRendererProps): JSX.Element {
    const knownException = useMemo(() => KnownExceptionRegistry.match(exception), [exception])

    const hasProperStackTrace = useMemo(() => {
        const stackTrace = exception.stacktrace
        if (stackTrace === null || stackTrace === undefined) {
            return false
        }

        if (!stackTrace.frames || stackTrace.frames.length === 0) {
            return false
        }

        if (stackTrace.frames.some((frame) => frame === null || typeof frame !== 'object')) {
            return false
        }

        return true
    }, [exception])

    return (
        <div className={className}>
            <div>{renderExceptionHeader(exception)}</div>
            <div>
                {match(exception.stacktrace)
                    .when(
                        () => !hasProperStackTrace,
                        () => renderUndefinedTrace(exception, knownException)
                    )
                    .when(
                        (stack) => stack!.type === 'resolved',
                        (stack) => {
                            let filteredFrames = frameFilter ? stack!.frames.filter(frameFilter) : stack!.frames
                            return match(filteredFrames)
                                .when(
                                    (frames) => Array.isArray(frames) && frames.length > 0,
                                    (frames) => renderResolvedTrace(frames, exception, knownException)
                                )
                                .otherwise(() => renderFilteredTrace(stack!.frames, exception, knownException))
                        }
                    )
                    .otherwise(() => null)}
            </div>
        </div>
    )
}
