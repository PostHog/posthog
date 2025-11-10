import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCollapse, IconExpand, IconSort } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

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

    return (
        <LemonCard className="overflow-hidden p-0" hoverEffect={false}>
            {/* Header */}
            <div className="flex items-center justify-between bg-surface-primary p-3">
                <div className="flex items-center gap-2">
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
                <div
                    className="p-2 space-y-1 max-h-[600px] overflow-y-auto bg-primary border-t border-border"
                    onScroll={handleScroll}
                >
                    {sessionEvents?.map((event, index) => (
                        <SessionEventItem
                            key={event.id}
                            event={{ ...event, fullyLoaded: true } as RecordingEventType}
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
