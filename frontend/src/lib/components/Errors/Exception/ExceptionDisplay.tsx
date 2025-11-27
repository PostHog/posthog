import { match } from 'ts-pattern'

import { ErrorTrackingException, ErrorTrackingStackFrame } from '../types'

type StackTraceRenderer = (frames: ErrorTrackingStackFrame[], exception: ErrorTrackingException) => React.ReactNode

export type ExceptionDisplayProps = {
    className?: string
    exception: ErrorTrackingException
    frameFilter?: (frame: ErrorTrackingStackFrame) => boolean
    renderExceptionHeader: (exception: ErrorTrackingException) => React.ReactNode

    renderEmptyTrace: (exception: ErrorTrackingException) => React.ReactNode
    renderResolvedTrace: StackTraceRenderer
    renderFilteredTrace: (exception: ErrorTrackingException) => React.ReactNode
}

export function ExceptionDisplay({
    className,
    exception,
    frameFilter,
    renderExceptionHeader,
    renderEmptyTrace,
    renderResolvedTrace,
    renderFilteredTrace,
}: ExceptionDisplayProps): JSX.Element {
    return (
        <div className={className}>
            <div className="exception-header">{renderExceptionHeader(exception)}</div>
            <div className="exception-stacktrace">
                {match(exception.stacktrace)
                    .when(
                        (stack) => stack === null || stack === undefined || stack.frames.length === 0,
                        () => renderEmptyTrace(exception)
                    )
                    .when(
                        (stack) => stack!.type === 'resolved',
                        (stack) => {
                            let frames = frameFilter ? stack!.frames.filter(frameFilter) : stack!.frames
                            return match(frames)
                                .when(
                                    (frames) => Array.isArray(frames) && frames.length > 0,
                                    (frames) => renderResolvedTrace(frames, exception)
                                )
                                .otherwise(() => renderFilteredTrace(exception))
                        }
                    )
                    .when(
                        (stack) => stack!.type === 'raw',
                        () => null
                    )
                    .otherwise(() => null)}
            </div>
        </div>
    )
}
