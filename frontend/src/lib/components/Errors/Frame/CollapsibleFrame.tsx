import { useState } from 'react'

import { CollapsiblePrimitive } from 'lib/ui/CollapsiblePrimitive/CollapsiblePrimitive'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrameContent } from './CollapsibleFrameContent'
import { CollapsibleFrameHeader } from './CollapsibleFrameHeader'

export interface CollapsibleFrameProps {
    frame: ErrorTrackingStackFrame
    record: ErrorTrackingStackFrameRecord
    onOpenChange?: (open: boolean) => void
}

export function CollapsibleFrame({ frame, record }: CollapsibleFrameProps): JSX.Element {
    let [expanded, setExpanded] = useState(false)
    return (
        <CollapsiblePrimitive open={expanded} onOpenChange={setExpanded} disabled={!record || !record.context}>
            <CollapsibleFrameHeader frame={frame} expanded={expanded} record={record} />
            <CollapsibleFrameContent frame={frame} record={record} />
        </CollapsiblePrimitive>
    )
}
