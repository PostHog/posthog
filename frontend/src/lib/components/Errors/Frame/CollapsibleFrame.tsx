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

export function CollapsibleFrame({ frame, record, onOpenChange }: CollapsibleFrameProps): JSX.Element {
    let [expanded, setExpanded] = useState(false)
    const handleOpenChange = (open: boolean): void => {
        setExpanded(open)
        onOpenChange?.(open)
    }
    return (
        <CollapsiblePrimitive open={expanded} onOpenChange={handleOpenChange}>
            <CollapsibleFrameHeader frame={frame} expanded={expanded} record={record} />
            <CollapsibleFrameContent frame={frame} record={record} />
        </CollapsiblePrimitive>
    )
}
