import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCollapse, IconExpand, IconSort } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime, humanFriendlyDuration } from 'lib/utils'

import { RecordingEventType } from '~/types'

import { sessionProfileLogic } from '../sessionProfileLogic'
import { SessionEventItem } from './SessionEventItem'

export interface SessionEventsListProps {
    events: RecordingEventType[] | null
    totalEventCount?: number | null
    isLoading?: boolean
    isLoadingMore?: boolean
    hasMoreEvents?: boolean
    onLoadEventDetails?: (eventId: string, eventName: string) => void
    onLoadMoreEvents?: () => void
    sortOrder: 'asc' | 'desc'
    onSortOrderChange: (sortOrder: 'asc' | 'desc') => void
}

export function SessionEventsList(): JSX.Element {
    const {
        sessionEvents,
        totalEventCount,
        isInitialLoading,
        isLoadingMore,
        hasMoreEvents,
        sortOrder,
        eventsListFolded,
    } = useValues(sessionProfileLogic)
    const { loadEventDetails, loadMoreSessionEvents, setSortOrder, setEventsListFolded } =
        useActions(sessionProfileLogic)
    const [expandedIndices, setExpandedIndices] = useState<Set<number>>(new Set())

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

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        if (!hasMoreEvents || isLoadingMore || !loadMoreSessionEvents) {
            return
        }

        const target = e.currentTarget
        const scrollBottom = target.scrollHeight - target.scrollTop - target.clientHeight

        // Load more when within 200px of bottom
        if (scrollBottom < 200) {
            loadMoreSessionEvents()
        }
    }

    if (isInitialLoading) {
        return (
            <LemonCard className="p-6">
                <div className="text-muted-alt text-center">Loading events...</div>
            </LemonCard>
        )
    }

    if (!sessionEvents || sessionEvents?.length === 0) {
        return (
            <LemonCard className="p-6">
                <div className="text-muted-alt text-center">No events found</div>
            </LemonCard>
        )
    }

    // When sorted ASC, first event is oldest (startTime), last is newest (endTime)
    // When sorted DESC, first event is newest (endTime), last is oldest (startTime)
    const firstEvent = dayjs(sessionEvents[0].timestamp)
    const lastEvent = dayjs(sessionEvents[sessionEvents.length - 1].timestamp)
    const startTime = sortOrder === 'asc' ? firstEvent : lastEvent
    const endTime = sortOrder === 'asc' ? lastEvent : firstEvent
    const durationSeconds = startTime && endTime ? endTime.diff(startTime, 'second') : 0

    return (
        <LemonCard className="overflow-hidden" hoverEffect={false}>
            {/* Header */}
            <div className="flex items-center justify-between bg-surface-primary p-3 border-b border-border">
                <div className="flex items-center gap-3">
                    <LemonButton
                        size="small"
                        icon={eventsListFolded ? <IconExpand /> : <IconCollapse />}
                        onClick={() => setEventsListFolded(!eventsListFolded)}
                    />
                    <div>
                        <h3 className="text-lg font-semibold">
                            Events (
                            {totalEventCount !== null && totalEventCount !== undefined
                                ? totalEventCount
                                : sessionEvents.length}
                            )
                        </h3>
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
                    <LemonButton
                        size="small"
                        icon={<IconSort className={clsx({ 'rotate-180': sortOrder === 'asc' })} />}
                        onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                        tooltip={sortOrder === 'asc' ? 'Sorted: Oldest first' : 'Sorted: Newest first'}
                    >
                        {sortOrder === 'asc' ? 'Oldest first' : 'Newest first'}
                    </LemonButton>
                    <LemonButton size="small" onClick={handleCollapseAll}>
                        Collapse All
                    </LemonButton>
                </div>
            </div>

            {/* Events List */}
            {!eventsListFolded && (
                <div className="p-4 space-y-2 max-h-[600px] overflow-y-auto" onScroll={handleScroll}>
                    {sessionEvents?.map((event, index) => (
                        <SessionEventItem
                            key={event.id}
                            event={event}
                            index={index}
                            isExpanded={expandedIndices.has(index)}
                            onToggleExpand={handleToggleExpand}
                            onLoadEventDetails={loadEventDetails}
                        />
                    ))}
                    {hasMoreEvents && (
                        <div className="text-center py-4 text-muted-alt">
                            {isLoadingMore ? 'Loading more events...' : 'Scroll for more'}
                        </div>
                    )}
                </div>
            )}
        </LemonCard>
    )
}
