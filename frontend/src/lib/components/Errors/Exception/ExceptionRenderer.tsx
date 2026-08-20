import { useMemo } from 'react'
import { match } from 'ts-pattern'

import { ErrorTrackingException, ErrorTrackingStackFrame } from '../types'
import { hasUsableStackTrace } from '../utils'
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

    const hasProperStackTrace = useMemo(() => hasUsableStackTrace(exception), [exception])

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
