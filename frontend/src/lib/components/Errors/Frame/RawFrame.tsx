import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { formatFrameResolvedName, formatFrameSource } from '../utils'

export function RawFrame({
    frame,
    record,
}: {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord
}): JSX.Element {
    const resolvedName = formatFrameResolvedName(frame)
    const source = formatFrameSource(frame)
    return (
        <>
            <p className="font-mono indent-[1rem] whitespace-no-wrap mb-0 line-clamp-1">
                {source}
                {frame.line ? `, line: ${frame.line}` : ''}
                {resolvedName ? `, in: ${resolvedName}` : ''}
            </p>
            {record && record.context?.line.line && (
                <p className="font-mono indent-[2rem] whitespace-no-wrap mb-0 text-tertiary line-clamp-1">
                    {record.context?.line.line}
                </p>
            )}
        </>
    )
}
