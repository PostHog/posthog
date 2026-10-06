import posthog from 'posthog-js'
import { useState } from 'react'

import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrameContent } from './CollapsibleFrameContent'
import { CollapsibleFrameHeader } from './CollapsibleFrameHeader'
import { FrameUnavailablePanel, getFrameUnavailableReason } from './FrameUnavailablePanel'

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
    const hasSource = !!record?.context || recordLoading
    // A frame without source code opens a reason panel instead. Local state keeps it out of the
    // shared expansion state, so it does not count as stack trace exploration.
    const [reasonOpen, setReasonOpen] = useState(false)

    const onReasonOpenChange = (open: boolean): void => {
        setReasonOpen(open)
        if (open) {
            posthog.capture('error_tracking_frame_unavailable_clicked', {
                reason: getFrameUnavailableReason(frame),
                lang: frame.lang,
                in_app: frame.in_app,
                resolved: frame.resolved,
            })
        }
    }

    return (
        <Collapsible
            variant="container"
            open={hasSource ? expanded : reasonOpen}
            onOpenChange={hasSource ? onExpandedChange : onReasonOpenChange}
        >
            <CollapsibleFrameHeader frame={frame} expanded={expanded} record={record} recordLoading={recordLoading} />
            {hasSource ? (
                <CollapsibleFrameContent frame={frame} record={record} />
            ) : (
                <FrameUnavailablePanel frame={frame} />
            )}
        </Collapsible>
    )
}
