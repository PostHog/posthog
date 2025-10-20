import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'

import { EnrichedSegment, EnrichedSegmentKeyActions, SegmentOutcome } from '~/types'

import { formatDuration, getIcon } from './utils'

interface SegmentCardProps {
    segment: EnrichedSegment
    outcome?: SegmentOutcome
    keyActions?: EnrichedSegmentKeyActions
    hasFailures: boolean
}

export function SegmentCard({ segment, outcome, keyActions, hasFailures }: SegmentCardProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    const icon = getIcon(!!outcome?.success)
    const buttonIcon = <IconChevronRight className={`w-3 h-3 transition-transform ${!isExpanded ? '' : 'rotate-90'}`} />

    return (
        <div className="border rounded bg-bg-3000 p-2">
            <div className="flex items-start gap-2">
                <span className="text-sm font-bold mt-0.5">{icon}</span>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-sm">{segment.name}</span>
                        {hasFailures && (
                            <span className="text-xs text-danger bg-danger-highlight px-1.5 py-0.5 rounded">
                                {pluralize(segment.meta?.failure_count || 0, 'issue')}
                            </span>
                        )}
                    </div>

                    {outcome?.summary && <p className="text-xs text-muted mb-2">{outcome.summary}</p>}

                    <div className="flex gap-3 text-xs text-muted mb-2">
                        <span>{segment.meta?.events_count || 0} events</span>
                        <span>{keyActions?.events?.length || 0} key actions</span>
                        <span>{formatDuration(segment.meta?.duration || 0)}</span>
                    </div>

                    {keyActions && keyActions.events && keyActions.events.length > 0 && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => setIsExpanded(!isExpanded)}
                            icon={buttonIcon}
                            children={`${isExpanded ? 'Hide' : 'Show'} key actions`}
                        />
                    )}

                    {isExpanded && keyActions?.events && (
                        <div className="mt-2 space-y-1.5 pl-2 border-l-2 border-border">
                            {keyActions.events.map((action, idx) => (
                                <div key={idx} className="text-xs">
                                    <div className="flex items-start gap-1.5">
                                        {action.exception ? (
                                            <span className="text-danger">⚠</span>
                                        ) : action.confusion ? (
                                            <span className="text-warning">?</span>
                                        ) : action.abandonment ? (
                                            <span className="text-muted">⊗</span>
                                        ) : (
                                            <span className="text-muted">•</span>
                                        )}
                                        <div className="flex-1">
                                            <span className="text-default">{action.description}</span>
                                            {action.event && <span className="text-muted ml-1">({action.event})</span>}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
