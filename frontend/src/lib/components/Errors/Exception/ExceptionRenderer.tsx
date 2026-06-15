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
    renderExceptionHeader: (exception: ErrorTrackingException) => React.ReactNode

    renderUndefinedTrace: (exception: ErrorTrackingException, knownException?: KnownException) => React.ReactNode
    renderResolvedTrace: StackTraceRenderer
}

export function ExceptionRenderer({
    className,
    exception,
    renderExceptionHeader,
    renderUndefinedTrace,
    renderResolvedTrace,
}: ExceptionRendererProps): JSX.Element {
    const knownException = useMemo(() => KnownExceptionRegistry.match(exception), [exception])

    const hasProperStackTrace = useMemo(() => {
        const stackTrace = exception.stacktrace
        if (stackTrace === null || stackTrace === undefined) {
            return false
        }

        if (!Array.isArray(stackTrace.frames) || stackTrace.frames.length === 0) {
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
                        (stack) => renderResolvedTrace(stack!.frames, exception, knownException)
                    )
                    .otherwise(() => null)}
            </div>
        </div>
    )
}
