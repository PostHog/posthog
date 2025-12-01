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
                                />
                            )}
                            renderFilteredTrace={() => {
                                setShowAllFrames(true)
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
                                            onOpenChange={onFirstFrameExpanded}
                                        />
                                    )}
                                />
                            )}
                            renderEmptyTrace={(exception) => <EmptyStackTrace exception={exception} />}
                        />
                    )
                }}
            />
        </div>
    )
}
