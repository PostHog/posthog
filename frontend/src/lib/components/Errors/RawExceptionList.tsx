import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { ExceptionDisplay } from './Exception/ExceptionDisplay'
import { ExceptionHeader } from './Exception/ExceptionHeader'
import { ExceptionListDisplay } from './ExceptionList/ExceptionListDisplay'
import { EmptyStacktraceDisplay } from './StackTrace/EmptyStackTraceDisplay'
import { ResolvedStackTraceDisplay } from './StackTrace/ResolvedStackTraceDisplay'
import { errorPropertiesLogic } from './errorPropertiesLogic'
import { ErrorTrackingStackFrame } from './types'

export function RawExceptionList({
    showAllFrames,
    setShowAllFrames,
    className,
}: {
    showAllFrames: boolean
    setShowAllFrames: (value: boolean) => void
    className?: string
}): JSX.Element {
    const { exceptionList, getExceptionFingerprint, exceptionAttributes, stackFrameRecords } =
        useValues(errorPropertiesLogic)
    // const { stackFrameRecords } = useValues(stackFrameLogic)
    // const [hasCalledOnFirstExpanded, setHasCalledOnFirstExpanded] = useState<boolean>(false)

    // const handleFrameExpanded = (): void => {
    //     if (onFirstFrameExpanded && !hasCalledOnFirstExpanded) {
    //         setHasCalledOnFirstExpanded(true)
    //         onFirstFrameExpanded()
    //     }
    // }

    return (
        <div className={cn('flex flex-col gap-y-2', className)}>
            <ExceptionListDisplay
                exceptionList={exceptionList}
                renderException={(exception) => {
                    const part = getExceptionFingerprint(exception.id)
                    return (
                        <ExceptionDisplay
                            exception={exception}
                            frameFilter={frameFilter(showAllFrames)}
                            renderExceptionHeader={(exception) => (
                                <ExceptionHeader
                                    exception={exception}
                                    loading={false}
                                    fingerprint={part}
                                    runtime={exceptionAttributes?.runtime}
                                />
                            )}
                            renderFilteredTrace={() => {
                                setShowAllFrames(true)
                                return null
                            }}
                            renderResolvedTrace={(frames: ErrorTrackingStackFrame[]) => (
                                <ResolvedStackTraceDisplay
                                    frames={frames}
                                    stackFrameRecords={stackFrameRecords}
                                    renderFrame={(frame) => frame.source}
                                />
                            )}
                            renderEmptyTrace={(exception) => <EmptyStacktraceDisplay exception={exception} />}
                        />
                    )
                }}
            />
        </div>
    )
}

function frameFilter(showAllFrames: boolean) {
    return (frame: ErrorTrackingStackFrame) => {
        if (showAllFrames) {
            return true
        }
        return frame.in_app
    }
}
