import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { CollapsibleExceptionHeader } from '../Exception/CollapsibleExceptionHeader'
import { ExceptionRenderer } from '../Exception/ExceptionRenderer'
import { CollapsibleFrame } from '../Frame/CollapsibleFrame'
import { EmptyStackTrace } from '../StackTrace/EmptyStackTrace'
import { StackTraceRenderer } from '../StackTrace/StackTraceRenderer'
import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame } from '../types'
import { createFrameFilter } from '../utils'
import { ExceptionListRenderer } from './ExceptionListRenderer'

export function CollapsibleExceptionList({
    showAllFrames,
    setShowAllFrames,
    className,
    onFrameOpenChange,
}: {
    showAllFrames: boolean
    setShowAllFrames: (value: boolean) => void
    onFrameOpenChange?: (open: boolean) => void
    className?: string
}): JSX.Element {
    const { exceptionList, getExceptionFingerprint, exceptionAttributes, stackFrameRecords, stackFrameRecordsLoading } =
        useValues(errorPropertiesLogic)

    return (
        <div className={cn('flex flex-col gap-y-2', className)}>
            <ExceptionListRenderer
                exceptionList={exceptionList}
                renderException={(exception, index) => {
                    const part = getExceptionFingerprint(exception.id)
                    return (
                        <ExceptionRenderer
                            exception={exception}
                            frameFilter={createFrameFilter(showAllFrames)}
                            renderExceptionHeader={(exception) => (
                                <CollapsibleExceptionHeader
                                    exception={exception}
                                    loading={false}
                                    fingerprint={part}
                                    runtime={exceptionAttributes?.runtime}
                                />
                            )}
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
                                    className="border-1 rounded overflow-hidden divide-y divide-solid"
                                    stackFrameRecords={stackFrameRecords}
                                    renderFrame={(frame, record) => (
                                        <CollapsibleFrame
                                            frame={frame}
                                            record={record}
                                            recordLoading={stackFrameRecordsLoading}
                                            onOpenChange={onFrameOpenChange}
                                        />
                                    )}
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
