import './Playlist.scss'

import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonBadge, LemonButton, LemonCollapse, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { range } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

import { RecordingsUniversalFiltersEmbedButton } from '../filters/RecordingsUniversalFiltersEmbed'
import { SessionRecordingPreview } from './SessionRecordingPreview'
import { SessionRecordingsPlaylistTopSettings } from './SessionRecordingsPlaylistSettings'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

const SCROLL_TRIGGER_OFFSET = 100

export type PlaylistProps = {
    listEmptyState: JSX.Element
    title?: string
    footerActions?: JSX.Element
    pinnedRecordings?: SessionRecordingType[]
    otherRecordings?: SessionRecordingType[]
    loading?: boolean
    hasNext?: boolean
    activeItemId?: string | null
    type?: 'filters' | 'collection'
    shortId?: string
    canMixFiltersAndPinned?: boolean
    logicKey?: string
    showFilters?: boolean
}

type Section = {
    key: string
    title: JSX.Element
    items: SessionRecordingType[]
    initiallyOpen: boolean
    footer?: JSX.Element
}

function buildSections(
    pinnedRecordings: SessionRecordingType[],
    otherRecordings: SessionRecordingType[],
    loading: boolean,
    hasNext: boolean,
    onLoadMore?: () => void
): Section[] {
    const sections: Section[] = []

    if (pinnedRecordings.length > 0) {
        sections.push({
            key: 'pinned',
            title: (
                <span className="flex gap-1 items-center">
                    Pinned recordings
                    <LemonBadge.Number count={pinnedRecordings.length} status="muted" size="small" />
                </span>
            ),
            items: pinnedRecordings,
            initiallyOpen: true,
        })
    }

    sections.push({
        key: 'other',
        title: (
            <span className="flex gap-1 items-center">
                Results
                <LemonBadge.Number count={otherRecordings.length} status="muted" size="small" />
            </span>
        ),
        items: otherRecordings,
        initiallyOpen: pinnedRecordings.length === 0,
        footer: (
            <div className="p-4 h-10 flex items-center justify-center gap-2 text-secondary">
                {loading ? (
                    <>
                        <Spinner textColored /> Loading older recordings
                    </>
                ) : hasNext ? (
                    <LemonButton onClick={() => onLoadMore?.()}>Load more</LemonButton>
                ) : (
                    'No more results'
                )}
            </div>
        ),
    })

    return sections
}

export function Playlist({
    title,
    footerActions,
    listEmptyState,
    pinnedRecordings: propsPinnedRecordings,
    otherRecordings: propsOtherRecordings,
    loading: propsLoading,
    hasNext: propsHasNext,
    activeItemId: propsActiveItemId,
    type = 'filters',
    shortId,
    canMixFiltersAndPinned = true,
    logicKey,
    showFilters = false,
}: PlaylistProps): JSX.Element {
    const {
        pinnedRecordings: logicPinnedRecordings,
        otherRecordings: logicOtherRecordings,
        sessionRecordingsResponseLoading,
        hasNext: logicHasNext,
        activeSessionRecordingId,
        filters,
        totalFiltersCount,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { maybeLoadSessionRecordings, setFilters } = useActions(sessionRecordingsPlaylistLogic)

    const notebookNode = useNotebookNode()
    const embedded = !!notebookNode

    const headerActions = (
        <SessionRecordingsPlaylistTopSettings filters={filters} setFilters={setFilters} type={type} shortId={shortId} />
    )

    const filterActions =
        !showFilters || notebookNode || (!canMixFiltersAndPinned && !!logicKey) ? null : (
            <RecordingsUniversalFiltersEmbedButton
                filters={filters}
                setFilters={setFilters}
                totalFiltersCount={totalFiltersCount}
                currentSessionRecordingId={activeSessionRecordingId}
            />
        )

    const pinnedRecordings = propsPinnedRecordings ?? logicPinnedRecordings
    const otherRecordings = propsOtherRecordings ?? logicOtherRecordings
    const loading = propsLoading ?? sessionRecordingsResponseLoading
    const hasNext = propsHasNext ?? logicHasNext
    const activeItemId = (propsActiveItemId === undefined ? activeSessionRecordingId : propsActiveItemId) ?? null

    const onLoadMore = (): void => {
        maybeLoadSessionRecordings('older')
    }

    const sections = buildSections(pinnedRecordings, otherRecordings, !!loading, hasNext, onLoadMore)

    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    const initiallyOpenSections = sections.filter((s) => s.initiallyOpen).map((s) => s.key)

    const lastScrollPositionRef = useRef(0)

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
        const scrollingDown = scrollTop > lastScrollPositionRef.current

        if (scrollingDown && scrollHeight - scrollTop - clientHeight < SCROLL_TRIGGER_OFFSET) {
            maybeLoadSessionRecordings('older')
        } else if (!scrollingDown && scrollTop < SCROLL_TRIGGER_OFFSET) {
            maybeLoadSessionRecordings('newer')
        }

        lastScrollPositionRef.current = scrollTop
    }

    const sectionsWithItems = sections.filter((s) => s.items.length > 0)
    const sectionCount = sectionsWithItems.length
    const itemsCount = sections.flatMap((s) => s.items).length

    return (
        <div className="flex flex-col h-full">
            {filterActions && (
                <DraggableToNotebook className="mb-2" href={urls.replay(ReplayTabs.Home, filters)}>
                    {filterActions}
                </DraggableToNotebook>
            )}
            <div
                ref={playlistRef}
                data-attr="session-recordings-playlist"
                className={cn('Playlist w-full h-full overflow-hidden', {
                    'Playlist--wide': size !== 'small',
                    'Playlist--embedded': embedded,
                })}
            >
                <div className="Playlist__list flex flex-col relative overflow-hidden h-full w-full">
                    <div className="flex flex-col relative w-full bg-bg-light overflow-hidden h-full Playlist__list border border-primary rounded">
                        <DraggableToNotebook href={urls.replay(ReplayTabs.Home, filters)}>
                            <div className="flex flex-col gap-1">
                                <div className="shrink-0 bg-bg-3000 relative flex justify-between items-center gap-0.5 whitespace-nowrap border-b">
                                    {title && <TitleWithCount title={title} count={itemsCount} />}
                                    {headerActions}
                                </div>
                                <LemonTableLoader loading={loading} />
                            </div>
                        </DraggableToNotebook>
                        <div className="overflow-y-auto flex-1" onScroll={handleScroll}>
                            {sectionCount > 1 ? (
                                <LemonCollapse
                                    defaultActiveKeys={initiallyOpenSections}
                                    panels={sectionsWithItems.map((s) => ({
                                        key: s.key,
                                        header: s.title,
                                        content: (
                                            <SectionContent
                                                section={s}
                                                loading={!!loading}
                                                activeItemId={activeItemId}
                                                emptyState={listEmptyState}
                                            />
                                        ),
                                        className: 'p-0',
                                    }))}
                                    multiple
                                    embedded
                                    size="small"
                                />
                            ) : sectionCount === 1 ? (
                                <SectionContent
                                    section={sectionsWithItems[0]}
                                    loading={!!loading}
                                    activeItemId={activeItemId}
                                    emptyState={listEmptyState}
                                />
                            ) : loading ? (
                                <LoadingState />
                            ) : (
                                listEmptyState
                            )}
                        </div>
                        <div className="shrink-0 relative flex justify-between items-center gap-0.5 whitespace-nowrap">
                            {footerActions}
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

function SectionContent({
    section,
    loading,
    activeItemId,
    emptyState,
}: {
    section: Section
    loading: boolean
    activeItemId: SessionRecordingType['id'] | null
    emptyState: PlaylistProps['listEmptyState']
}): JSX.Element {
    const { setSelectedRecordingId } = useActions(sessionRecordingsPlaylistLogic)

    return section.items.length > 0 ? (
        <ListSection {...section} onClick={(item) => setSelectedRecordingId(item.id)} activeItemId={activeItemId} />
    ) : loading ? (
        <LoadingState />
    ) : (
        emptyState
    )
}

function ListSection({
    items,
    footer,
    onClick,
    activeItemId,
}: Section & {
    onClick: (item: SessionRecordingType) => void
    activeItemId: SessionRecordingType['id'] | null
}): JSX.Element {
    return (
        <>
            {items.map((item) => (
                <div key={item.id} className="border-b" onClick={() => onClick(item)}>
                    <SessionRecordingPreview recording={item} isActive={item.id === activeItemId} selectable />
                </div>
            ))}
            {footer}
        </>
    )
}

const LoadingState = (): JSX.Element => {
    return (
        <>
            {range(5).map((i) => (
                <div key={i} className="p-4 flex flex-col gap-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton className="w-1/3 h-4" />
                </div>
            ))}
        </>
    )
}
