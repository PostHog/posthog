import { useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime, humanFriendlyDuration } from 'lib/utils'

import { RecordingEventType } from '~/types'

import { SessionEventItem } from './SessionEventItem'

export interface SessionEventsListProps {
    events: RecordingEventType[] | null
    isLoading?: boolean
    onLoadEventDetails?: (eventId: string) => void
}

export function SessionEventsList({ events, isLoading, onLoadEventDetails }: SessionEventsListProps): JSX.Element {
    const [expandedIndices, setExpandedIndices] = useState<Set<number>>(new Set())
    const [isFolded, setIsFolded] = useState(false)

    const handleToggleExpand = (index: number): void => {
        setExpandedIndices((prev) => {
            const newSet = new Set(prev)
            if (newSet.has(index)) {
                newSet.delete(index)
            } else {
                newSet.add(index)
            }
            return newSet
        })
    }

    const handleCollapseAll = (): void => {
        setExpandedIndices(new Set())
    }

    if (isLoading) {
        return (
            <LemonCard className="p-6">
                <div className="text-muted-alt text-center">Loading events...</div>
            </LemonCard>
        )
    }

    if (!events || events.length === 0) {
        return (
            <LemonCard className="p-6">
                <div className="text-muted-alt text-center">No events found</div>
            </LemonCard>
        )
    }

    const startTime = events.length > 0 ? dayjs(events[0].timestamp) : null
    const endTime = events.length > 0 ? dayjs(events[events.length - 1].timestamp) : null
    const durationSeconds = startTime && endTime ? endTime.diff(startTime, 'second') : 0

    return (
        <LemonCard className="overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between bg-surface-primary p-3 border-b border-border">
                <div className="flex items-center gap-3">
                    <LemonButton
                        size="small"
                        icon={isFolded ? <IconExpand /> : <IconCollapse />}
                        onClick={() => setIsFolded((state) => !state)}
                    />
                    <div>
                        <h3 className="text-lg font-semibold">Events ({events.length})</h3>
                        {startTime && (
                            <div className="text-xs text-muted-alt">
                                {humanFriendlyDetailedTime(startTime)}
                                {durationSeconds > 0 && (
                                    <span> - Duration: {humanFriendlyDuration(durationSeconds)}</span>
                                )}
                            </div>
                        )}
                    </div>
                </div>
                <div className="flex gap-2">
                    <LemonButton size="small" onClick={handleCollapseAll}>
                        Collapse All
                    </LemonButton>
                </div>
            </div>

            {/* Events List */}
            {!isFolded && (
                <div className="p-4 space-y-2 max-h-[600px] overflow-y-auto">
                    {events.map((event, index) => (
                        <SessionEventItem
                            key={event.id}
                            event={event}
                            index={index}
                            isExpanded={expandedIndices.has(index)}
                            onToggleExpand={handleToggleExpand}
                            onLoadEventDetails={onLoadEventDetails}
                        />
                    ))}
                </div>
            )}
        </LemonCard>
    )
}
