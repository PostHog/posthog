import { useCallback, useRef, useState } from 'react'

import { useScrollObserver } from 'lib/hooks/useScrollObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import type { DashboardBasicType } from '~/types'

export interface DashboardWidgetPlacementDestination {
    dashboard: DashboardBasicType
    /** When set, the row is disabled and this explains why (e.g. widget already on that dashboard). */
    disabledReason?: string
}

interface DashboardWidgetPlacementMenuProps {
    destinations: DashboardWidgetPlacementDestination[]
    onSelect: (dashboard: DashboardBasicType) => void
    onOpen?: () => void
    loading?: boolean
    loaded?: boolean
    hasMore?: boolean
    onLoadMore?: () => void
    /** Submenu trigger label (e.g. "Move to" vs "Copy to"). */
    label?: string
    /** When there are no destinations, the trigger stays visible but disabled (avoids hiding the action). */
    emptyDisabledReason?: string
}

export function DashboardWidgetPlacementMenu({
    destinations,
    onSelect,
    onOpen,
    loading = false,
    loaded = false,
    hasMore = false,
    onLoadMore,
    label = 'Move to',
    emptyDisabledReason = 'No other dashboards',
}: DashboardWidgetPlacementMenuProps): JSX.Element {
    const [searchTerm, setSearchTermState] = useState('')
    const showInitialLoading = !loaded
    const hasMoreRef = useRef(hasMore)
    const onLoadMoreRef = useRef(onLoadMore)
    hasMoreRef.current = hasMore
    onLoadMoreRef.current = onLoadMore

    const loadMoreDestinations = useCallback(() => {
        if (hasMoreRef.current) {
            onLoadMoreRef.current?.()
        }
    }, [])

    const destinationsScrollRef = useScrollObserver({
        onScrollBottom: loadMoreDestinations,
    })

    const handleSearchChange = useCallback((value: string) => {
        setSearchTermState(value)
    }, [])

    // TODO: make use Fuse search (might be overkill though)
    const filteredDestinations =
        searchTerm.trim() === ''
            ? destinations
            : destinations.filter((entry) =>
                  (entry.dashboard.name || 'Untitled').toLowerCase().includes(searchTerm.toLowerCase())
              )
    const destinationsStateRef = useRef({
        filteredDestinations,
        handleSearchChange,
        hasMore,
        loading,
        onSelect,
        searchTerm,
        showInitialLoading,
    })
    destinationsStateRef.current = {
        filteredDestinations,
        handleSearchChange,
        hasMore,
        loading,
        onSelect,
        searchTerm,
        showInitialLoading,
    }

    const DestinationsLabel = useCallback(() => {
        const { filteredDestinations, handleSearchChange, hasMore, loading, onSelect, searchTerm, showInitialLoading } =
            destinationsStateRef.current
        return (
            <div className="w-72 p-2">
                {showInitialLoading ? (
                    <div aria-label="Loading dashboards">
                        <LemonSkeleton.Row className="h-8 mb-1" repeat={5} fade />
                    </div>
                ) : (
                    <>
                        <LemonInput
                            type="search"
                            placeholder="Search dashboards"
                            value={searchTerm}
                            onChange={handleSearchChange}
                            size="small"
                            fullWidth
                            allowClear
                            onClick={(event) => event.stopPropagation()}
                            autoFocus
                        />
                        <div ref={destinationsScrollRef} className="mt-1 max-h-[60vh] overflow-y-auto">
                            {filteredDestinations.map(({ dashboard, disabledReason }) => (
                                <LemonButton
                                    key={dashboard.id}
                                    fullWidth
                                    disabledReason={disabledReason}
                                    onClick={() => !disabledReason && onSelect(dashboard)}
                                >
                                    {dashboard.name || <i>Untitled</i>}
                                </LemonButton>
                            ))}
                            {!loading && filteredDestinations.length === 0 && (
                                <div className="px-2 py-1 text-secondary">No dashboards match this search</div>
                            )}
                            {loading && hasMore && <LemonSkeleton.Row className="h-8 mb-1" repeat={2} fade />}
                        </div>
                    </>
                )}
            </div>
        )
    }, [destinationsScrollRef])

    const items: LemonMenuItems = [{ custom: true, label: DestinationsLabel }]

    if (!destinations.length && !showInitialLoading && !onOpen) {
        return (
            <LemonButton fullWidth disabledReason={emptyDisabledReason}>
                {label}
            </LemonButton>
        )
    }

    return (
        <LemonMenu
            items={items}
            placement="right-start"
            fallbackPlacements={['left-start']}
            onVisibilityChange={(visible) => {
                if (visible) {
                    onOpen?.()
                }
            }}
        >
            <LemonButton fullWidth>{label}</LemonButton>
        </LemonMenu>
    )
}
