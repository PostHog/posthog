import './StackTraces.scss'

import { useValues } from 'kea'
import { MouseEvent } from 'react'

import { cn } from 'lib/utils/css-classes'

import { ExceptionDisplay } from './Exception/ExceptionDisplay'
import { ExceptionHeader } from './Exception/ExceptionHeader'
import { ExceptionListDisplay } from './ExceptionList/ExceptionListDisplay'
import { CollapsibleFrame } from './Frame/CollapsibleFrame'
import { EmptyStacktraceDisplay } from './StackTrace/EmptyStackTraceDisplay'
import { ResolvedStackTraceDisplay } from './StackTrace/ResolvedStackTraceDisplay'
import { errorPropertiesLogic } from './errorPropertiesLogic'
import { stackFrameLogic } from './stackFrameLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, FingerprintRecordPart } from './types'

type FrameContextClickHandler = (ctx: ErrorTrackingStackFrameContext, e: MouseEvent) => void

export function ChainedStackTraces({
    showAllFrames,
    setShowAllFrames,
    embedded = false,
    className,
}: {
    fingerprintRecords?: FingerprintRecordPart[]
    showAllFrames: boolean
    setShowAllFrames: (value: boolean) => void
    embedded?: boolean
    onFrameContextClick?: FrameContextClickHandler
    onFirstFrameExpanded?: () => void
    className?: string
}): JSX.Element {
    const { exceptionList, getExceptionFingerprint, exceptionAttributes } = useValues(errorPropertiesLogic)
    const { stackFrameRecords } = useValues(stackFrameLogic)
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
                                    embedded={embedded}
                                    renderFrame={(frame, record) => <CollapsibleFrame frame={frame} record={record} />}
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
