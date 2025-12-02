import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { ExceptionRenderer } from '../Exception/ExceptionRenderer'
import { RawExceptionHeader } from '../Exception/RawExceptionHeader'
import { RawFrame } from '../Frame/RawFrame'
import { EmptyStackTrace } from '../StackTrace/EmptyStackTrace'
import { StackTraceRenderer } from '../StackTrace/StackTraceRenderer'
import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame } from '../types'
import { createFrameFilter } from '../utils'
import { ExceptionListRenderer } from './ExceptionListRenderer'

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
            <ExceptionListRenderer
                exceptionList={exceptionList}
                renderException={(exception, index) => {
                    return (
                        <ExceptionRenderer
                            exception={exception}
                            frameFilter={createFrameFilter(showAllFrames)}
                            renderExceptionHeader={(exception) => <RawExceptionHeader exception={exception} />}
                            renderFilteredTrace={() => {
                                if (!showAllFrames && index == 0) {
                                    // Always show frames on the first exception
                                    setShowAllFrames(true)
                                }
                                return null
                            }}
                            renderResolvedTrace={(frames: ErrorTrackingStackFrame[]) => (
                                <StackTraceRenderer
                                    frames={frames}
                                    stackFrameRecords={stackFrameRecords}
                                    renderFrame={(frame, record) => <RawFrame frame={frame} record={record} />}
                                />
                            )}
                            renderUndefinedTrace={(exception, known) => (
                                <EmptyStackTrace exception={exception} knownException={known} />
                            )}
                        />
                    )
                }}
            />
        </div>
    )
}
