import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { ExceptionDisplay } from './Exception/ExceptionDisplay'
import { ExceptionListDisplay } from './ExceptionList/ExceptionListDisplay'
import { RawFrame } from './Frame/RawFrame'
import { EmptyStacktraceDisplay } from './StackTrace/EmptyStackTraceDisplay'
import { ResolvedStackTraceDisplay } from './StackTrace/ResolvedStackTraceDisplay'
import { errorPropertiesLogic } from './errorPropertiesLogic'
import { ErrorTrackingStackFrame } from './types'
import { createFrameFilter, formatExceptionDisplay } from './utils'

export function RawExceptionList({
    showAllFrames,
    setShowAllFrames,
    className,
}: {
    showAllFrames: boolean
    setShowAllFrames: (value: boolean) => void
    className?: string
}): JSX.Element {
    const { exceptionList, stackFrameRecords } = useValues(errorPropertiesLogic)

    return (
        <div className={cn('flex flex-col gap-y-2', className)}>
            <ExceptionListDisplay
                exceptionList={exceptionList}
                renderException={(exception) => {
                    return (
                        <ExceptionDisplay
                            exception={exception}
                            frameFilter={createFrameFilter(showAllFrames)}
                            renderExceptionHeader={(exception) => (
                                <p className="font-mono mb-0 font-bold line-clamp-1">
                                    {formatExceptionDisplay(exception)}
                                </p>
                            )}
                            renderFilteredTrace={() => {
                                setShowAllFrames(true)
                                return null
                            }}
                            renderResolvedTrace={(frames: ErrorTrackingStackFrame[]) => (
                                <ResolvedStackTraceDisplay
                                    frames={frames}
                                    stackFrameRecords={stackFrameRecords}
                                    renderFrame={(frame, record) => <RawFrame frame={frame} record={record} />}
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
