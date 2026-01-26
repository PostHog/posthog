import './Playlist.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ReactNode, useRef, useState } from 'react'

import { IconMagicWand, IconSidebarClose } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonSkeleton,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { range } from 'lib/utils'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { RecordingsUniversalFiltersEmbedButton } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { SessionRecordingsPlaylistTopSettings } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistTroubleshooting'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

const SCROLL_TRIGGER_OFFSET = 100

type PlaylistSectionBase = {
    key: string
    title?: ReactNode
    initiallyOpen?: boolean
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
}

export function Playlist({
    title,
    type,
    logicKey,
    isSynthetic,
    description,
    selectInitialItem,
}: PlaylistProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { askSidePanelMax } = useActions(maxGlobalLogic)

    const { isPlaylistCollapsed } = useValues(playerSettingsLogic)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)

    const playlistListRef = useRef<HTMLDivElement>(null)
    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

    const notebookNode = useNotebookNode()
    const embedded = !!notebookNode

    // bound outside here
    const {
        filters,
        activeSessionRecordingId,
        totalFiltersCount,
        sessionRecordingsResponseLoading,
        pinnedRecordings,
        otherRecordings,
        hasNext,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { maybeLoadSessionRecordings, setFilters, setSelectedRecordingId } =
        useActions(sessionRecordingsPlaylistLogic)

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
            render: ({ item, isActive }) => <SessionRecordingPreview recording={item} isActive={isActive} selectable />,
            initiallyOpen: true,
        })
    } else {
        sections.push({
            key: 'other',
            title: (
                <div className="flex flex-row deprecated-space-x-1 items-center">
                    <span>Results</span>
                    <LemonBadge.Number count={otherRecordings.length} status="muted" size="small" />
                </div>
            ),
            items: otherRecordings,
            initiallyOpen: !pinnedRecordings.length,
            render: ({ item, isActive }) => <SessionRecordingPreview recording={item} isActive={isActive} selectable />,
            footer: (
                <div className="p-4">
                    <div className="h-10 flex items-center justify-center gap-2 text-secondary">
                        {sessionRecordingsResponseLoading ? (
                            <>
                                <Spinner textColored /> Loading older recordings
                            </>
                        ) : hasNext ? (
                            <LemonButton onClick={() => maybeLoadSessionRecordings('older')}>Load more</LemonButton>
                        ) : (
                            'No more results'
                        )}
                    </div>
                </div>
            ),
        })
    }

    const firstItem = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        ?.find((s) => s.items.length > 0)?.items[0]
    const sectionCount = sections.length
    const itemsCount = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        .flatMap((s) => s.items).length

    const initiallyOpenSections = sections.filter((s) => s.initiallyOpen).map((s) => s.key)
    const [openSections, setOpenSections] = useState<string[]>(initiallyOpenSections)

    const onChangeOpenSections = (activeKeys: string[]): void => {
        setOpenSections(activeKeys)
    }

    const [controlledActiveItemId, setControlledActiveItemId] = useState<SessionRecordingType['id'] | null>(
        selectInitialItem && firstItem ? firstItem.id : null
    )

    const onChangeActiveItem = (item: SessionRecordingType): void => {
        setControlledActiveItemId(item.id)
        setSelectedRecordingId(item.id)
    }

    const activeItemId = activeSessionRecordingId === undefined ? controlledActiveItemId : activeSessionRecordingId

    const listEmptyState =
        type === 'collection' ? (
            <CollectionEmptyState isSynthetic={isSynthetic} description={description} />
        ) : (
            <ListEmptyState />
        )

    // Show collapsed view
    if (isPlaylistCollapsed) {
        return (
            <div className="flex items-center justify-center h-full w-full px-0">
                <LemonButton
                    icon={<IconSidebarClose className={clsx(!isPlaylistCollapsed && 'rotate-180')} />}
                    onClick={() => setPlaylistCollapsed(false)}
                    tooltip="Expand playlist"
                    size="xsmall"
                    noPadding
                    data-attr="expand-playlist"
                />
            </div>
        )
    }

    return (
        <div className="flex flex-col min-w-60 h-full">
            {!notebookNode && (
                <DraggableToNotebook className="mb-2" href={urls.replay(ReplayTabs.Home, filters)}>
                    <RecordingsUniversalFiltersEmbedButton
                        filters={filters}
                        setFilters={setFilters}
                        totalFiltersCount={totalFiltersCount}
                        currentSessionRecordingId={activeSessionRecordingId}
                    />
                </DraggableToNotebook>
            )}
            <div
                ref={playlistRef}
                data-attr="session-recordings-playlist"
                className={clsx(
                    'Playlist flex flex-row items-start justify-start h-full w-full min-w-60 min-h-82 overflow-hidden border rounded',
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
                        <DraggableToNotebook href={urls.replay(ReplayTabs.Home, filters)}>
                            <div className="flex flex-col gap-1">
                                <div className="shrink-0 bg-bg-3000 relative flex justify-between items-center gap-0.5 whitespace-nowrap border-b">
                                    {title && <TitleWithCount title={title} count={itemsCount} />}
                                    <div className="flex items-center gap-0.5">
                                        <LemonButton
                                            icon={
                                                <IconSidebarClose
                                                    className={clsx(!isPlaylistCollapsed && 'rotate-180')}
                                                />
                                            }
                                            onClick={() => setPlaylistCollapsed(true)}
                                            tooltip="Collapse playlist"
                                            size="xsmall"
                                            data-attr="collapse-playlist"
                                        />
                                        <SessionRecordingsPlaylistTopSettings
                                            filters={filters}
                                            setFilters={setFilters}
                                            type={type}
                                            shortId={logicKey}
                                        />
                                    </div>
                                </div>
                                <LemonTableLoader loading={sessionRecordingsResponseLoading} />
                            </div>
                        </DraggableToNotebook>
                        <div className="overflow-y-auto flex-1 min-h-0" onScroll={handleScroll} ref={contentRef}>
                            {sectionCount > 1 ? (
                                <LemonCollapse
                                    defaultActiveKeys={openSections}
                                    panels={sections.map((s) => {
                                        return {
                                            key: s.key,
                                            header: s.title ?? '',
                                            content: (
                                                <SectionContent
                                                    section={s}
                                                    loading={!!sessionRecordingsResponseLoading}
                                                    setActiveItemId={onChangeActiveItem}
                                                    activeItemId={activeItemId}
                                                    emptyState={listEmptyState}
                                                />
                                            ),
                                            className: 'p-0',
                                        }
                                    })}
                                    onChange={onChangeOpenSections}
                                    multiple
                                    embedded
                                    size="small"
                                />
                            ) : sectionCount === 1 ? (
                                <SectionContent
                                    section={sections[0]}
                                    loading={!!sessionRecordingsResponseLoading}
                                    setActiveItemId={onChangeActiveItem}
                                    activeItemId={activeItemId}
                                    emptyState={listEmptyState}
                                />
                            ) : sessionRecordingsResponseLoading ? (
                                <LoadingState />
                            ) : (
                                listEmptyState
                            )}
                        </div>
                    </div>
                    {featureFlags[FEATURE_FLAGS.MAX_SESSION_SUMMARIZATION_BUTTON] && (
                        <LemonButton
                            icon={<IconMagicWand />}
                            type="primary"
                            onClick={() => {
                                askSidePanelMax('Summarize recordings based on the current filters')
                            }}
                            fullWidth
                            size="small"
                            className="mt-2"
                            disabledReason={!firstItem ? 'No recordings in the list' : undefined}
                        >
                            Summarize these recordings
                            <LemonTag type="warning" size="small" className="ml-auto uppercase">
                                Beta
                            </LemonTag>
                        </LemonButton>
                    )}
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

const ListEmptyState = (): JSX.Element => {
    const { sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)

    return (
        <div className="p-3 text-sm text-secondary">
            {sessionRecordingsAPIErrored ? (
                <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
            ) : unusableEventsInFilter.length ? (
                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
            ) : (
                <div className="flex flex-col gap-2">
                    <SessionRecordingsPlaylistTroubleshooting />
                </div>
            )}
        </div>
    )
}

const CollectionEmptyState = ({
    isSynthetic,
    description,
}: {
    isSynthetic?: boolean
    description?: string
}): JSX.Element => {
    const { sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)

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
                    <p>
                        To add recordings to this collection, go to the{' '}
                        <Link to={urls.replay(ReplayTabs.Home)}>Recordings</Link> tab, click on a recording, then click
                        "+ Add to collection" and select this collection from the list.
                    </p>
                </div>
            )}
        </div>
    )
}

function SectionContent({
    section,
    loading,
    activeItemId,
    setActiveItemId,
    emptyState,
}: {
    section: PlaylistSection
    loading: boolean
    activeItemId: SessionRecordingType['id'] | null
    setActiveItemId: (item: SessionRecordingType) => void
    emptyState: JSX.Element
}): JSX.Element {
    return 'content' in section ? (
        <>{section.content}</>
    ) : 'items' in section && !!section.items.length ? (
        <ListSection {...section} onClick={setActiveItemId} activeItemId={activeItemId} />
    ) : loading ? (
        <LoadingState />
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
}: PlaylistRecordingPreviewBlock & {
    onClick: (item: SessionRecordingType) => void
    activeItemId: SessionRecordingType['id'] | null
}): JSX.Element {
    return (
        <>
            {items.length > 0
                ? items.map((item) => (
                      <div key={item.id} className="border-b" onClick={() => onClick(item)}>
                          {render({ item, isActive: item.id === activeItemId })}
                      </div>
                  ))
                : null}
            {footer}
        </>
    )
}

const LoadingState = (): JSX.Element => {
    return (
        <>
            {range(5).map((i) => (
                <div key={i} className="p-4 deprecated-space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton className="w-1/3 h-4" />
                </div>
            ))}
        </>
    )
}

/**
 * TODO add docs on how to enrich custom events with session_id and link to it from here
 */
const UnusableEventsWarning = (props: { unusableEventsInFilter: string[] }): JSX.Element => {
    return (
        <LemonBanner type="warning">
            <p>Cannot use these events to filter for session recordings:</p>
            <li className="my-1">
                {props.unusableEventsInFilter.map((event) => (
                    <span key={event}>"{event}"</span>
                ))}
            </li>
            <p>
                Events have to have a <PropertyKeyInfo value="$session_id" /> to be used to filter recordings. This is
                added automatically by{' '}
                <Link to="https://posthog.com/docs/libraries/js" target="_blank">
                    the Web SDK
                </Link>
                ,{' '}
                <Link to="https://posthog.com/docs/libraries" target="_blank">
                    and the Mobile SDKs (Android, iOS, React Native and Flutter)
                </Link>
            </p>
        </LemonBanner>
    )
}
