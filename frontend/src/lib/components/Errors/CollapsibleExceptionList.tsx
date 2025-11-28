import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { ExceptionDisplay } from './Exception/ExceptionDisplay'
import { ExceptionHeader } from './Exception/ExceptionHeader'
import { ExceptionListDisplay } from './ExceptionList/ExceptionListDisplay'
import { CollapsibleFrame } from './Frame/CollapsibleFrame'
import { EmptyStacktraceDisplay } from './StackTrace/EmptyStackTraceDisplay'
import { ResolvedStackTraceDisplay } from './StackTrace/ResolvedStackTraceDisplay'
import { errorPropertiesLogic } from './errorPropertiesLogic'
import { ErrorTrackingStackFrame } from './types'
import { createFrameFilter } from './utils'

export function CollapsibleExceptionList({
    showAllFrames,
    setShowAllFrames,
    className,
    onFirstFrameExpanded,
}: {
    showAllFrames: boolean
    setShowAllFrames: (value: boolean) => void
    onFirstFrameExpanded?: () => void
    className?: string
}): JSX.Element {
    const { exceptionList, getExceptionFingerprint, exceptionAttributes, stackFrameRecords } =
        useValues(errorPropertiesLogic)
    // const firstFrameExpansion
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
                            frameFilter={createFrameFilter(showAllFrames)}
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
                                    className="border-1 rounded overflow-hidden divide-y divide-solid"
                                    stackFrameRecords={stackFrameRecords}
                                    renderFrame={(frame, record) => (
                                        <CollapsibleFrame
                                            frame={frame}
                                            record={record}
                                            onOpenChange={onFirstFrameExpanded}
                                        />
                                    )}
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
