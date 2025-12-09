import { useState } from 'react'

import { CollapsiblePrimitive } from 'lib/ui/CollapsiblePrimitive/CollapsiblePrimitive'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrameContent } from './CollapsibleFrameContent'
import { CollapsibleFrameHeader } from './CollapsibleFrameHeader'

export interface CollapsibleFrameProps {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord
    recordLoading: boolean
    onOpenChange?: (open: boolean) => void
}

export function CollapsibleFrame({ frame, record, recordLoading, onOpenChange }: CollapsibleFrameProps): JSX.Element {
    let [expanded, setExpanded] = useState(false)
    const handleOpenChange = (open: boolean): void => {
        setExpanded(open)
        onOpenChange?.(open)
    }
    return (
        <CollapsiblePrimitive open={expanded} onOpenChange={handleOpenChange}>
            <CollapsibleFrameHeader frame={frame} expanded={expanded} record={record} recordLoading={recordLoading} />
            <CollapsibleFrameContent frame={frame} record={record} />
        </CollapsiblePrimitive>
    )
}
