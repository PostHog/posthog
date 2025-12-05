import { cn } from 'lib/utils/css-classes'

import { KeyedStackFrameRecords } from '../Frame/stackFrameLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'

export interface StackTraceRendererProps {
    className?: string
    embedded?: boolean
    frames: ErrorTrackingStackFrame[]
    stackFrameRecords: KeyedStackFrameRecords
    renderFrame: (frame: ErrorTrackingStackFrame, record?: ErrorTrackingStackFrameRecord) => React.ReactNode
    onFrameExpanded?: () => void
}

export function StackTraceRenderer({
    frames,
    stackFrameRecords,
    renderFrame,
    className,
}: StackTraceRendererProps): JSX.Element {
    return (
        <div className={cn('overflow-hidden', className)}>
            {frames.map((frame: ErrorTrackingStackFrame, idx) => (
                <div key={idx}>{renderFrame(frame, stackFrameRecords[frame.raw_id])}</div>
            ))}
        </div>
    )
}
