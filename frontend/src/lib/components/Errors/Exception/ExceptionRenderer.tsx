import { match } from 'ts-pattern'

import { ErrorTrackingException, ErrorTrackingStackFrame } from '../types'

type StackTraceRenderer = (frames: ErrorTrackingStackFrame[], exception: ErrorTrackingException) => React.ReactNode

export type ExceptionRendererProps = {
    className?: string
    exception: ErrorTrackingException
    frameFilter?: (frame: ErrorTrackingStackFrame) => boolean
    renderExceptionHeader: (exception: ErrorTrackingException) => React.ReactNode

    renderEmptyTrace: (exception: ErrorTrackingException) => React.ReactNode
    renderResolvedTrace: StackTraceRenderer
    renderFilteredTrace: (exception: ErrorTrackingException) => React.ReactNode
}

export function ExceptionRenderer({
    className,
    exception,
    frameFilter,
    renderExceptionHeader,
    renderEmptyTrace,
    renderResolvedTrace,
    renderFilteredTrace,
}: ExceptionRendererProps): JSX.Element {
    return (
        <div className={className}>
            <div>{renderExceptionHeader(exception)}</div>
            <div>
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
