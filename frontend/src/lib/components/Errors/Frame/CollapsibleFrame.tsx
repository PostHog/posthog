import { CollapsiblePrimitive } from 'lib/ui/CollapsiblePrimitive/CollapsiblePrimitive'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrameContent } from './CollapsibleFrameContent'
import { CollapsibleFrameHeader } from './CollapsibleFrameHeader'

export interface CollapsibleFrameProps {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord
    recordLoading: boolean
    expanded: boolean
    onExpandedChange: (expanded: boolean) => void
}

export function CollapsibleFrame({
    frame,
    record,
    recordLoading,
    expanded,
    onExpandedChange,
}: CollapsibleFrameProps): JSX.Element {
    return (
        <CollapsiblePrimitive open={expanded} onOpenChange={onExpandedChange}>
            <CollapsibleFrameHeader frame={frame} expanded={expanded} record={record} recordLoading={recordLoading} />
            <CollapsibleFrameContent frame={frame} record={record} />
        </CollapsiblePrimitive>
    )
}
