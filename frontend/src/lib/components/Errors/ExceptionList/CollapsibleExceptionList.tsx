import { useValues } from 'kea'
import { useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'

import { CollapsibleExceptionHeader } from '../Exception/CollapsibleExceptionHeader'
import { ExceptionRenderer } from '../Exception/ExceptionRenderer'
import { CollapsibleFrame } from '../Frame/CollapsibleFrame'
import { EmptyStackTrace } from '../StackTrace/EmptyStackTrace'
import { FilteredStackTrace } from '../StackTrace/FilteredStackTrace'
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
    const {
        exceptionList,
        getExceptionFingerprint,
        exceptionAttributes,
        stackFrameRecords,
        stackFrameRecordsLoading,
        hasInAppFrames,
    } = useValues(errorPropertiesLogic)

    useEffect(() => {
        if (!hasInAppFrames) {
            setShowAllFrames(true)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [hasInAppFrames])

    return (
        <div className={cn('flex flex-col gap-y-2', className)}>
            <ExceptionListRenderer
                exceptionList={exceptionList}
                renderException={(exception) => {
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
                                    truncate={false}
                                />
                            )}
                            renderFilteredTrace={(frames) => (
                                <FilteredStackTrace
                                    framesCount={frames.length}
                                    exceptionCount={exceptionList.length}
                                    onShowAllFrames={() => setShowAllFrames(true)}
                                />
                            )}
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
