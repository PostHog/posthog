import { LemonCollapse } from '@posthog/lemon-ui'

import { KeyedStackFrameRecords } from '../stackFrameLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'

export interface ResolvedStackTraceDisplayProps {
    className?: string
    embedded?: boolean
    frames: ErrorTrackingStackFrame[]
    stackFrameRecords: KeyedStackFrameRecords
    renderFrameHeader: (frame: ErrorTrackingStackFrame, record: ErrorTrackingStackFrameRecord) => JSX.Element
    renderFrameContent: (frame: ErrorTrackingStackFrame, record: ErrorTrackingStackFrameRecord) => JSX.Element | null
    onFrameExpanded?: () => void
}

export function ResolvedStackTraceDisplay({
    frames,
    stackFrameRecords,
    embedded = false,
    renderFrameHeader,
    renderFrameContent,
    onFrameExpanded,
}: ResolvedStackTraceDisplayProps): JSX.Element {
    const panels = frames.map((frame: ErrorTrackingStackFrame, idx) => {
        return {
            key: idx,
            header: renderFrameHeader(frame, stackFrameRecords[frame.raw_id]),
            content: renderFrameContent(frame, stackFrameRecords[frame.raw_id]),
            className: 'p-0',
        }
    })
    return <LemonCollapse embedded={embedded} multiple panels={panels} size="xsmall" onChange={onFrameExpanded} />
}
