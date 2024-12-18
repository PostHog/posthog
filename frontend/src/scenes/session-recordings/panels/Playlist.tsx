import { LemonBanner, LemonButton, LemonCollapse, LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PlaylistProps, PlaylistSection } from 'lib/components/Playlist/Playlist'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { range } from 'lib/utils'
import { useRef } from 'react'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

import { SessionRecordingPreview } from '../playlist/SessionRecordingPreview'
import { DEFAULT_RECORDING_FILTERS, sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'
import {
    SessionRecordingPlaylistBottomSettings,
    SessionRecordingsPlaylistTopSettings,
} from '../playlist/SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from '../playlist/SessionRecordingsPlaylistTroubleshooting'

const SCROLL_TRIGGER_OFFSET = 100

export const PanelPlaylist = (): JSX.Element => {
    const {
        filters,
        pinnedRecordings,
        sessionRecordingsResponseLoading,
        otherRecordings,
        activeSessionRecordingId,
        hasNext,
    } = useValues(sessionRecordingsPlaylistLogic({ updateSearchParams: true }))
    const { maybeLoadSessionRecordings, setSelectedRecordingId, setFilters, setShowOtherRecordings } = useActions(
        sessionRecordingsPlaylistLogic({ updateSearchParams: true })
    )

    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'

    const pinnedDescription = isTestingSaved ? 'Saved' : 'Pinned'

    const sections: PlaylistSection<SessionRecordingType>[] = []

    if (pinnedRecordings.length) {
        sections.push({
            key: 'pinned',
            title: `${pinnedDescription} recordings`,
            items: pinnedRecordings,
            render: ({ item, isActive }) => (
                <SessionRecordingPreview recording={item} isActive={isActive} pinned={true} />
            ),
            initiallyOpen: true,
        })
    }

    sections.push({
        key: 'other',
        title: 'Other recordings',
        items: otherRecordings,
        render: ({ item, isActive }) => <SessionRecordingPreview recording={item} isActive={isActive} pinned={false} />,
        footer: (
            <div className="p-4">
                <div className="h-10 flex items-center justify-center gap-2 text-muted-alt">
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

    return (
        <List
            title="Results"
            notebooksHref={urls.replay(ReplayTabs.Home, filters)}
            loading={sessionRecordingsResponseLoading}
            sections={sections}
            headerActions={<SessionRecordingsPlaylistTopSettings filters={filters} setFilters={setFilters} />}
            footerActions={<SessionRecordingPlaylistBottomSettings />}
            onScrollListEdge={(edge) => {
                if (edge === 'top') {
                    maybeLoadSessionRecordings('newer')
                } else {
                    maybeLoadSessionRecordings('older')
                }
            }}
            activeItemId={activeSessionRecordingId ?? null}
            setActiveItemId={(item) => setSelectedRecordingId(item.id)}
            onChangeSections={(activeSections) => setShowOtherRecordings(activeSections.includes('other'))}
            emptyState={<ListEmptyState />}
        />
    )
}

const ListEmptyState = (): JSX.Element => {
    const { filters, sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <div className="p-3 text-sm text-muted-alt">
            {sessionRecordingsAPIErrored ? (
                <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
            ) : unusableEventsInFilter.length ? (
                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
            ) : (
                <div className="flex flex-col items-center space-y-2">
                    {filters.date_from === DEFAULT_RECORDING_FILTERS.date_from ? (
                        <>
                            <span>No matching recordings found</span>
                            <LemonButton
                                type="secondary"
                                data-attr="expand-replay-listing-from-default-seven-days-to-twenty-one"
                                onClick={() => setFilters({ date_from: '-30d' })}
                            >
                                Search over the last 30 days
                            </LemonButton>
                        </>
                    ) : (
                        <SessionRecordingsPlaylistTroubleshooting />
                    )}
                </div>
            )}
        </div>
    )
}

function UnusableEventsWarning(props: { unusableEventsInFilter: string[] }): JSX.Element {
    // TODO add docs on how to enrich custom events with session_id and link to it from here
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

function List<
    T extends {
        id: string | number
        [key: string]: any
    }
>({
    notebooksHref,
    setActiveItemId,
    headerActions,
    footerActions,
    sections,
    onChangeSections,
    activeItemId,
    onScrollListEdge,
    loading,
    emptyState,
}: {
    title?: string
    notebooksHref: PlaylistProps<T>['notebooksHref']
    activeItemId: T['id'] | null
    setActiveItemId: (item: T) => void
    headerActions: PlaylistProps<T>['headerActions']
    footerActions: PlaylistProps<T>['footerActions']
    sections: PlaylistProps<T>['sections']
    onChangeSections?: (activeKeys: string[]) => void
    onScrollListEdge: PlaylistProps<T>['onScrollListEdge']
    loading: PlaylistProps<T>['loading']
    emptyState: PlaylistProps<T>['listEmptyState']
}): JSX.Element {
    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        // If we are scrolling down then check if we are at the bottom of the list
        if (e.currentTarget.scrollTop > lastScrollPositionRef.current) {
            const scrollPosition = e.currentTarget.scrollTop + e.currentTarget.clientHeight
            if (e.currentTarget.scrollHeight - scrollPosition < SCROLL_TRIGGER_OFFSET) {
                onScrollListEdge?.('bottom')
            }
        }

        // Same again but if scrolling to the top
        if (e.currentTarget.scrollTop < lastScrollPositionRef.current) {
            if (e.currentTarget.scrollTop < SCROLL_TRIGGER_OFFSET) {
                onScrollListEdge?.('top')
            }
        }

        lastScrollPositionRef.current = e.currentTarget.scrollTop
    }

    const initiallyOpenSections = sections.filter((s) => s.initiallyOpen).map((s) => s.key)

    return (
        <div className="bg-bg-light h-full flex flex-col">
            <DraggableToNotebook href={notebooksHref}>
                <div className="flex flex-col gap-1">
                    <div className="shrink-0 bg-bg-3000 relative flex justify-between items-center gap-0.5 whitespace-nowrap border-b">
                        {headerActions}
                    </div>
                    <LemonTableLoader loading={loading} />
                </div>
            </DraggableToNotebook>

            <div className="overflow-y-auto flex-1" onScroll={handleScroll} ref={contentRef}>
                {sections.flatMap((s) => s.items).length ? (
                    <>
                        {sections.length > 1 ? (
                            <LemonCollapse
                                defaultActiveKeys={initiallyOpenSections}
                                panels={sections.map((s) => ({
                                    key: s.key,
                                    header: s.title,
                                    content: (
                                        <ListSection {...s} activeItemId={activeItemId} onClick={setActiveItemId} />
                                    ),
                                    className: 'p-0',
                                }))}
                                onChange={onChangeSections}
                                multiple
                                embedded
                                size="small"
                            />
                        ) : (
                            <ListSection {...sections[0]} activeItemId={activeItemId} onClick={setActiveItemId} />
                        )}
                    </>
                ) : loading ? (
                    <LoadingState />
                ) : (
                    emptyState
                )}
            </div>
            <div className="shrink-0 relative flex justify-between items-center gap-0.5 whitespace-nowrap border-t">
                {footerActions}
            </div>
        </div>
    )
}

export function ListSection<
    T extends {
        id: string | number
        [key: string]: any
    }
>({
    items,
    render,
    footer,
    onClick,
    activeItemId,
}: PlaylistSection<T> & {
    onClick: (item: T) => void
    activeItemId: T['id'] | null
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
            {range(20).map((i) => (
                <div key={i} className="p-4 space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton className="w-1/3 h-4" />
                </div>
            ))}
        </>
    )
}
