import './Playlist.scss'

import { useVirtualizer } from '@tanstack/react-virtual'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode, useLayoutEffect, useRef, useState } from 'react'

import { IconSidebarClose } from '@posthog/icons'
import { LemonBadge, LemonBanner, LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { Heading, Text } from '@posthog/quill'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { RecordingsUniversalFiltersEmbedButton } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { ListCollapsedToggle } from 'scenes/session-recordings/playlist/ListCollapsedToggle'
import { ListLoadingState } from 'scenes/session-recordings/playlist/ListLoadingState'
import { ListLoadMoreFooter } from 'scenes/session-recordings/playlist/ListLoadMoreFooter'
import { ListOnlyLiveState } from 'scenes/session-recordings/playlist/ListOnlyLiveState'
import { OngoingRecordingsGroup } from 'scenes/session-recordings/playlist/OngoingRecordingsGroup'
import { playlistFiltersLogic } from 'scenes/session-recordings/playlist/playlistFiltersLogic'
import { splitOngoingRecordings } from 'scenes/session-recordings/playlist/playlistUtils'
import { QuillListCollapsedToggle } from 'scenes/session-recordings/playlist/QuillListCollapsedToggle'
import { QuillListLoadingState } from 'scenes/session-recordings/playlist/QuillListLoadingState'
import { QuillListLoadMoreFooter } from 'scenes/session-recordings/playlist/QuillListLoadMoreFooter'
import { QuillListNotice } from 'scenes/session-recordings/playlist/QuillListNotice'
import { QuillListOnlyLiveState } from 'scenes/session-recordings/playlist/QuillListOnlyLiveState'
import { QuillSelectedRecordingsBar } from 'scenes/session-recordings/playlist/QuillSelectedRecordingsBar'
import { QuillSessionRecordingsPlaylistTroubleshooting } from 'scenes/session-recordings/playlist/QuillSessionRecordingsPlaylistTroubleshooting'
import { QuillUnusableEventsWarning } from 'scenes/session-recordings/playlist/QuillUnusableEventsWarning'
import { ReplayFilterBar } from 'scenes/session-recordings/playlist/ReplayFilterBar'
import { isNewReplayLayout } from 'scenes/session-recordings/playlist/replayLayout'
import { ReplayListHeader } from 'scenes/session-recordings/playlist/ReplayListHeader'
import { SelectedRecordingsBar } from 'scenes/session-recordings/playlist/SelectedRecordingsBar'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { SessionRecordingPreviewFeed } from 'scenes/session-recordings/playlist/SessionRecordingPreviewFeed'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistTopSettings } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistTroubleshooting'
import { UnusableEventsWarning } from 'scenes/session-recordings/playlist/UnusableEventsWarning'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

const SCROLL_TRIGGER_OFFSET = 100
// Starting row height for the virtualizer; dynamic measurement corrects each row after it renders.
const ESTIMATED_ROW_HEIGHT = 56

type PlaylistSectionBase = {
    key: string
    title?: ReactNode
}

export type PlaylistRecordingPreviewBlock = PlaylistSectionBase & {
    items: SessionRecordingType[]
    render: ({ item, isActive }: { item: SessionRecordingType; isActive: boolean }) => JSX.Element
    footer?: JSX.Element
}

export type PlaylistContentBlock = PlaylistSectionBase & {
    content: ReactNode
}

export type PlaylistSection = PlaylistRecordingPreviewBlock | PlaylistContentBlock

export type PlaylistProps = {
    title?: string
    type?: 'filters' | 'collection'
    logicKey?: string
    isSynthetic?: boolean
    description?: string
    selectInitialItem?: boolean
    /**
     * Replaces the shared replay troubleshooting panel when a filters list comes back empty. Set it
     * on a surface that already knows why its list is empty, because the shared panel can only
     * offer the generic replay hints. Collections keep their own empty state.
     */
    listEmptyState?: JSX.Element
    watchLayout?: boolean
}

export function Playlist({
    title,
    type,
    logicKey,
    isSynthetic,
    description,
    selectInitialItem,
    listEmptyState,
    watchLayout = false,
}: PlaylistProps): JSX.Element {
    const { isPlaylistCollapsed, replayLayout } = useValues(playerSettingsLogic)
    const newLayout = watchLayout && isNewReplayLayout(replayLayout)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)
    const collapseButton = (
        <LemonButton
            icon={<IconSidebarClose className={clsx(!isPlaylistCollapsed && 'rotate-180')} />}
            onClick={() => setPlaylistCollapsed(true)}
            tooltip="Collapse playlist"
            size="xsmall"
            data-attr="collapse-playlist"
        />
    )

    const playlistListRef = useRef<HTMLDivElement>(null)
    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    const lastScrollPositionRef = useRef(0)
    // state, not a ref: the virtualizer must re-initialize when the scroll container mounts
    const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null)

    const notebookNode = useNotebookNode()
    const embedded = !!notebookNode
    const watchListHeader = newLayout && !notebookNode
    const watchFilterBar = watchListHeader && type !== 'collection'

    // bound outside here
    const {
        filters,
        activeSessionRecordingId,
        totalFiltersCount,
        sessionRecordingsResponseLoading,
        visiblePinnedRecordings: pinnedRecordings,
        otherRecordings,
        hasNext,
        selectedRecordingOutsideFilters,
        selectMode,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { maybeLoadSessionRecordings, setFilters, setSelectedRecordingId } =
        useActions(sessionRecordingsPlaylistLogic)
    const { setIsFiltersExpanded } = useActions(playlistFiltersLogic)

    const onScrollListEdge = (edge: 'bottom' | 'top'): void => {
        if (edge === 'top') {
            maybeLoadSessionRecordings('newer')
        } else {
            maybeLoadSessionRecordings('older')
        }
    }

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        if (e.currentTarget.scrollTop > lastScrollPositionRef.current) {
            const scrollPosition = e.currentTarget.scrollTop + e.currentTarget.clientHeight
            if (e.currentTarget.scrollHeight - scrollPosition < SCROLL_TRIGGER_OFFSET) {
                onScrollListEdge?.('bottom')
            }
        }

        if (e.currentTarget.scrollTop < lastScrollPositionRef.current) {
            if (e.currentTarget.scrollTop < SCROLL_TRIGGER_OFFSET) {
                onScrollListEdge?.('top')
            }
        }

        lastScrollPositionRef.current = e.currentTarget.scrollTop
    }

    const renderRow = ({ item, isActive }: { item: SessionRecordingType; isActive: boolean }): JSX.Element =>
        newLayout ? (
            <SessionRecordingPreviewFeed recording={item} isActive={isActive} selectable={selectMode} />
        ) : (
            <SessionRecordingPreview recording={item} isActive={isActive} selectable />
        )

    const { ongoing: ongoingRecordings, finished: finishedRecordings } = splitOngoingRecordings(
        otherRecordings,
        newLayout
    )

    const loadingState = newLayout ? <QuillListLoadingState /> : <ListLoadingState />
    const loadMoreFooterProps = {
        loading: !!sessionRecordingsResponseLoading,
        hasNext,
        dateFrom: filters.date_from,
        onLoadOlder: () => maybeLoadSessionRecordings('older'),
        onWidenDateRange: (dateFrom: string) => setFilters({ date_from: dateFrom }),
        onShowFilters: () => setIsFiltersExpanded(true),
    }

    const sections: PlaylistSection[] = []

    if (type === 'collection' || pinnedRecordings.length > 0) {
        sections.push({
            key: 'pinned',
            title: (
                <div className="flex flex-row deprecated-space-x-1 items-center">
                    <span>Pinned recordings</span>
                    <LemonBadge.Number count={pinnedRecordings.length} status="muted" size="small" />
                </div>
            ),
            items: pinnedRecordings,
            render: renderRow,
        })
    } else {
        sections.push({
            key: 'other',
            title: (
                <div className="flex flex-row deprecated-space-x-1 items-center">
                    <span>Results</span>
                    <LemonBadge.Number count={finishedRecordings.length} status="muted" size="small" />
                </div>
            ),
            items: finishedRecordings,
            render: renderRow,
            footer: newLayout ? (
                <QuillListLoadMoreFooter {...loadMoreFooterProps} />
            ) : (
                <ListLoadMoreFooter {...loadMoreFooterProps} />
            ),
        })
    }

    const firstItem = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        ?.find((s) => s.items.length > 0)?.items[0]
    const itemsCount = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        .flatMap((s) => s.items).length

    const [controlledActiveItemId, setControlledActiveItemId] = useState<SessionRecordingType['id'] | null>(
        selectInitialItem && firstItem ? firstItem.id : null
    )

    const onChangeActiveItem = (item: SessionRecordingType): void => {
        setControlledActiveItemId(item.id)
        setSelectedRecordingId(item.id)
    }

    const activeItemId = activeSessionRecordingId === undefined ? controlledActiveItemId : activeSessionRecordingId

    const selectedBarProps = (count: number): { count: number; loading: boolean; onShowAll: () => void } => ({
        count,
        loading: !!sessionRecordingsResponseLoading,
        onShowAll: () => setFilters({ session_ids: undefined }),
    })
    const onlyLiveProps = {
        hasNext,
        loading: !!sessionRecordingsResponseLoading,
        onLoadOlder: () => maybeLoadSessionRecordings('older'),
    }
    const emptyState =
        ongoingRecordings.length > 0 ? (
            newLayout ? (
                <QuillListOnlyLiveState {...onlyLiveProps} />
            ) : (
                <ListOnlyLiveState {...onlyLiveProps} />
            )
        ) : type === 'collection' ? (
            <CollectionEmptyState isSynthetic={isSynthetic} description={description} newLayout={newLayout} />
        ) : (
            <ListEmptyState listEmptyState={listEmptyState} newLayout={newLayout} />
        )

    // Show collapsed view
    if (isPlaylistCollapsed) {
        return newLayout ? (
            <QuillListCollapsedToggle onExpand={() => setPlaylistCollapsed(false)} />
        ) : (
            <ListCollapsedToggle onExpand={() => setPlaylistCollapsed(false)} />
        )
    }

    return (
        <div className="flex flex-col min-w-60 h-full">
            {watchFilterBar && (
                <div className="mb-2">
                    <ReplayFilterBar
                        filters={filters}
                        setFilters={setFilters}
                        totalFiltersCount={totalFiltersCount}
                        currentSessionRecordingId={activeSessionRecordingId}
                        onReload={() => maybeLoadSessionRecordings()}
                    />
                </div>
            )}
            {!watchListHeader && !notebookNode && type !== 'collection' && (
                <div className="mb-2 flex gap-2">
                    <DraggableToNotebook className="flex-1" href={urls.replay(ReplayTabs.Home, filters)}>
                        <RecordingsUniversalFiltersEmbedButton
                            filters={filters}
                            setFilters={setFilters}
                            totalFiltersCount={totalFiltersCount}
                            currentSessionRecordingId={activeSessionRecordingId}
                            onReload={() => maybeLoadSessionRecordings()}
                        />
                    </DraggableToNotebook>
                </div>
            )}
            {!!filters?.session_ids?.length &&
                (newLayout ? (
                    <QuillSelectedRecordingsBar {...selectedBarProps(filters.session_ids.length)} />
                ) : (
                    <SelectedRecordingsBar {...selectedBarProps(filters.session_ids.length)} />
                ))}
            <div
                ref={playlistRef}
                data-attr="session-recordings-playlist"
                className={clsx(
                    'Playlist flex flex-row items-start justify-start h-full w-full min-w-60 min-h-82 [[data-stacked]_&]:min-h-0 overflow-hidden border rounded',
                    {
                        'Playlist--wide': size !== 'small',
                        'Playlist--embedded border-0': embedded,
                    }
                )}
            >
                <div
                    ref={playlistListRef}
                    className="Playlist__list flex flex-col relative overflow-hidden h-full w-full"
                >
                    <div className="flex flex-col relative w-full bg-bg-light overflow-hidden h-full Playlist__list">
                        <div className="relative">
                            {watchListHeader && (
                                <ReplayListHeader
                                    filters={filters}
                                    setFilters={setFilters}
                                    onCollapse={() => setPlaylistCollapsed(true)}
                                    type={type}
                                    shortId={type === 'collection' ? logicKey : undefined}
                                />
                            )}
                            {!watchListHeader && (
                                <DraggableToNotebook href={urls.replay(ReplayTabs.Home, filters)}>
                                    <div className="shrink-0 bg-bg-3000 flex justify-between items-center gap-0.5 whitespace-nowrap border-b">
                                        {title && <TitleWithCount title={title} count={itemsCount} />}
                                        <div className="flex items-center gap-0.5 flex-1 min-w-0">
                                            <SessionRecordingsPlaylistTopSettings
                                                filters={filters}
                                                setFilters={setFilters}
                                                type={type}
                                                shortId={type === 'collection' ? logicKey : undefined}
                                            />
                                            <LemonDivider vertical className="my-1 mx-0.5" />
                                            {collapseButton}
                                        </div>
                                    </div>
                                </DraggableToNotebook>
                            )}
                            <LemonTableLoader loading={sessionRecordingsResponseLoading} />
                        </div>
                        {selectedRecordingOutsideFilters &&
                            (newLayout ? (
                                <QuillListNotice tone="warning" className="m-2">
                                    The recording you have open doesn't match the current filters. It stays in the list
                                    until you close it.
                                </QuillListNotice>
                            ) : (
                                <LemonBanner type="warning" className="m-2">
                                    The recording you have open doesn't match the current filters. It stays in the list
                                    until you close it.
                                </LemonBanner>
                            ))}
                        <div
                            className="overflow-y-auto flex-1 min-h-0 [scrollbar-gutter:stable] [scrollbar-width:thin]"
                            onScroll={handleScroll}
                            ref={setScrollEl}
                        >
                            <OngoingRecordingsGroup
                                count={ongoingRecordings.length}
                                holdsActive={ongoingRecordings.some((r) => r.id === activeItemId)}
                                defaultOpen={finishedRecordings.length === 0}
                            >
                                <ListSection
                                    key="ongoing"
                                    items={ongoingRecordings}
                                    render={renderRow}
                                    onClick={onChangeActiveItem}
                                    activeItemId={activeItemId}
                                    scrollEl={scrollEl}
                                />
                            </OngoingRecordingsGroup>
                            <SectionContent
                                section={sections[0]}
                                loading={!!sessionRecordingsResponseLoading}
                                loadingState={loadingState}
                                setActiveItemId={onChangeActiveItem}
                                activeItemId={activeItemId}
                                emptyState={emptyState}
                                scrollEl={scrollEl}
                            />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

const TitleWithCount = ({ title, count }: { title?: string; count: number }): JSX.Element => {
    return (
        <div className="flex items-center gap-0.5">
            {title && (
                <span className="flex flex-1 gap-1 items-center">
                    <span className="font-bold uppercase text-xxs tracking-wide">{title}</span>
                    <Tooltip
                        placement="bottom"
                        title={
                            <>
                                Showing {count} results.
                                <br />
                                Scrolling to the bottom or the top of the list will load older or newer results
                                respectively.
                            </>
                        }
                    >
                        <span className="rounded py-1 px-2 bg-border-light font-semibold select-none text-xxs">
                            {Math.min(999, count)}+
                        </span>
                    </Tooltip>
                </span>
            )}
        </div>
    )
}

const ListEmptyState = ({
    listEmptyState,
    newLayout,
}: Pick<PlaylistProps, 'listEmptyState'> & { newLayout: boolean }): JSX.Element => {
    const { sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)

    if (newLayout) {
        return (
            <div data-quill className="p-3 text-sm text-muted-foreground">
                {sessionRecordingsAPIErrored ? (
                    <QuillListNotice tone="destructive">Error while trying to load recordings.</QuillListNotice>
                ) : unusableEventsInFilter.length ? (
                    <QuillUnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
                ) : (
                    <div className="flex flex-col gap-2">
                        {listEmptyState ?? <QuillSessionRecordingsPlaylistTroubleshooting />}
                    </div>
                )}
            </div>
        )
    }
    return (
        <div className="p-3 text-sm text-secondary">
            {sessionRecordingsAPIErrored ? (
                <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
            ) : unusableEventsInFilter.length ? (
                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
            ) : (
                <div className="flex flex-col gap-2">
                    {listEmptyState ?? <SessionRecordingsPlaylistTroubleshooting />}
                </div>
            )}
        </div>
    )
}

const CollectionEmptyState = ({
    isSynthetic,
    description,
    newLayout,
}: {
    isSynthetic?: boolean
    description?: string
    newLayout: boolean
}): JSX.Element => {
    const { sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)

    if (newLayout) {
        return (
            <div data-quill className="p-3 text-sm text-muted-foreground">
                {sessionRecordingsAPIErrored ? (
                    <QuillListNotice tone="destructive">Error while trying to load recordings.</QuillListNotice>
                ) : unusableEventsInFilter.length ? (
                    <QuillUnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
                ) : (
                    <div className="flex flex-col gap-2">
                        <Heading size="sm" render={<h3 />} className="m-0">
                            {isSynthetic ? 'No recordings yet' : 'No recordings in this collection'}
                        </Heading>
                        <Text size="sm" variant="muted">
                            {isSynthetic
                                ? description || 'This collection is automatically populated.'
                                : 'Use "Add recordings" above to browse recordings and add them to this collection.'}
                        </Text>
                    </div>
                )}
            </div>
        )
    }
    return (
        <div className="p-3 text-sm text-secondary">
            {sessionRecordingsAPIErrored ? (
                <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
            ) : unusableEventsInFilter.length ? (
                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
            ) : isSynthetic ? (
                <div className="flex flex-col gap-2">
                    <h3 className="title text-secondary mb-0">No recordings yet</h3>
                    <p>{description || 'This collection is automatically populated.'}</p>
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    <h3 className="title text-secondary mb-0">No recordings in this collection</h3>
                    <p>Use "Add recordings" above to browse recordings and add them to this collection.</p>
                </div>
            )}
        </div>
    )
}

function SectionContent({
    section,
    loading,
    loadingState,
    activeItemId,
    setActiveItemId,
    emptyState,
    scrollEl,
}: {
    section: PlaylistSection
    loading: boolean
    loadingState: JSX.Element
    activeItemId: SessionRecordingType['id'] | null
    setActiveItemId: (item: SessionRecordingType) => void
    emptyState: JSX.Element
    scrollEl: HTMLDivElement | null
}): JSX.Element {
    return 'content' in section ? (
        <>{section.content}</>
    ) : 'items' in section && !!section.items.length ? (
        <ListSection {...section} onClick={setActiveItemId} activeItemId={activeItemId} scrollEl={scrollEl} />
    ) : loading ? (
        loadingState
    ) : (
        emptyState
    )
}

export function ListSection({
    items,
    render,
    footer,
    onClick,
    activeItemId,
    scrollEl,
}: PlaylistRecordingPreviewBlock & {
    onClick: (item: SessionRecordingType) => void
    activeItemId: SessionRecordingType['id'] | null
    scrollEl: HTMLDivElement | null
}): JSX.Element {
    const listRef = useRef<HTMLDivElement>(null)
    const [scrollMargin, setScrollMargin] = useState(0)

    const virtualizer = useVirtualizer({
        count: items.length,
        getScrollElement: () => scrollEl,
        estimateSize: () => ESTIMATED_ROW_HEIGHT,
        overscan: 10,
        getItemKey: (index) => items[index].id,
        scrollMargin,
    })

    // The list can sit below a banner or a pinned section inside the shared scroll container, and that
    // offset changes when those appear or collapse. Realign the virtualizer's origin on layout shifts.
    // The formula is scroll-invariant, so it only updates state on real shifts, not on every scroll frame.
    useLayoutEffect(() => {
        const listEl = listRef.current
        if (!listEl || !scrollEl || virtualizer.isScrolling) {
            return
        }
        const nextMargin =
            listEl.getBoundingClientRect().top - scrollEl.getBoundingClientRect().top + scrollEl.scrollTop
        setScrollMargin((current) => (Math.abs(current - nextMargin) > 1 ? nextMargin : current))
    })

    // Transformed absolute rows opt out of browser scroll anchoring, so compensate for
    // prepended items ("newer" loads) to keep the visible rows in place.
    const prevFirstIdRef = useRef(items[0]?.id)
    useLayoutEffect(() => {
        const prevFirstId = prevFirstIdRef.current
        prevFirstIdRef.current = items[0]?.id
        const insertedCount = items.findIndex((item) => item.id === prevFirstId)
        if (insertedCount > 0 && scrollEl && scrollEl.scrollTop > 0) {
            scrollEl.scrollTop += insertedCount * ESTIMATED_ROW_HEIGHT
        }
    }, [items, scrollEl])

    return (
        <>
            <div ref={listRef} className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
                {virtualizer.getVirtualItems().map((virtualItem) => {
                    const item = items[virtualItem.index]
                    return (
                        <div
                            key={virtualItem.key}
                            data-index={virtualItem.index}
                            ref={virtualizer.measureElement}
                            className="border-b absolute top-0 left-0 w-full"
                            style={{ transform: `translateY(${virtualItem.start - scrollMargin}px)` }}
                            onClick={() => onClick(item)}
                        >
                            {render({ item, isActive: item.id === activeItemId })}
                        </div>
                    )
                })}
            </div>
            {footer}
        </>
    )
}
