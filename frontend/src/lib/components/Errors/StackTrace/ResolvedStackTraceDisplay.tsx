import { KeyedStackFrameRecords } from '../stackFrameLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'

export interface ResolvedStackTraceDisplayProps {
    className?: string
    embedded?: boolean
    frames: ErrorTrackingStackFrame[]
    stackFrameRecords: KeyedStackFrameRecords
    renderFrame: (frame: ErrorTrackingStackFrame, record: ErrorTrackingStackFrameRecord) => JSX.Element
    onFrameExpanded?: () => void
}

export function ResolvedStackTraceDisplay({
    frames,
    stackFrameRecords,
    renderFrame,
}: ResolvedStackTraceDisplayProps): JSX.Element {
    return (
        <div className="border-1 rounded overflow-hidden divide-y divide-solid">
            {frames.map((frame: ErrorTrackingStackFrame, idx) => (
                <div key={idx}>{renderFrame(frame, stackFrameRecords[frame.raw_id])}</div>
            ))}
        </div>
    )
}
