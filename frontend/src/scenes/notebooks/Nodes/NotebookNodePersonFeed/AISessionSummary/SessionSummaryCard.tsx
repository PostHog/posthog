import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'

import { SessionSummary } from '~/types'

import { SegmentCard } from './SegmentCard'
import { formatDuration, getIcon } from './utils'

export interface SessionSummaryCardProps {
    sessionId: string
    summary: SessionSummary
}

export function SessionSummaryCard({ sessionId, summary }: SessionSummaryCardProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    const icon = getIcon(!!summary?.session_outcome?.success)

    const totalSegments = summary?.segments?.length || 0
    const totalEvents = summary?.segments?.reduce((acc, seg) => acc + (seg.meta?.events_count || 0), 0) || 0
    const totalKeyActions = summary?.key_actions?.reduce((acc, ka) => acc + (ka.events?.length || 0), 0) || 0
    const totalDuration = summary?.segments?.reduce((acc, seg) => acc + (seg.meta?.duration || 0), 0) || 0

    const buttonContent = (
        <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted">
                <span className="text-base font-bold">{icon}</span>
                <span className="font-mono">{sessionId}</span>
                <span>•</span>
                <span>{pluralize(totalSegments, 'segment', 'segments')}</span>
            </div>
            <p className="text-sm">{summary?.session_outcome?.description}</p>
            <div className="flex gap-4 text-xs text-muted pt-1">
                <span>{pluralize(totalEvents, 'event', 'events')}</span>
                <span>{pluralize(totalKeyActions, 'key action', 'key actions')}</span>
                <span>{formatDuration(totalDuration)} duration</span>
            </div>
        </div>
    )
    const buttonIcon = (
        <IconChevronRight className={`w-3 h-3 opacity-80 transition-transform ${!isExpanded ? '' : 'rotate-90'}`} />
    )

    return (
        <div className="border rounded bg-bg-light mb-2">
            <LemonButton
                onClick={() => setIsExpanded(!isExpanded)}
                icon={buttonIcon}
                className="w-full py-2 flex gap-2 hover:bg-surface-secondary transition-colors text-left"
                children={buttonContent}
            />

            {isExpanded && summary.segments && summary.segments.length > 0 && (
                <div className="p-3 border-t space-y-3">
                    <h4 className="font-semibold text-sm">Session Journey</h4>
                    {summary.segments.map((segment, idx) => {
                        const segmentOutcome = summary.segment_outcomes?.find((so) => so.segment_index === idx)
                        const segmentKeyActions = summary.key_actions?.find((ka) => ka.segment_index === idx)
                        const hasFailures = (segment.meta?.failure_count || 0) > 0

                        return (
                            <SegmentCard
                                key={idx}
                                segment={segment}
                                outcome={segmentOutcome}
                                keyActions={segmentKeyActions}
                                hasFailures={hasFailures}
                            />
                        )
                    })}
                </div>
            )}
        </div>
    )
}
