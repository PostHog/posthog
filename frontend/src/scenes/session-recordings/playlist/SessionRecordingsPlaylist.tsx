import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectSection, Link, Spinner } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Playlist, PlaylistSection } from 'lib/components/Playlist/Playlist'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { urls } from 'scenes/urls'

import { RecordingOrder } from '~/queries/schema'
import { RecordingUniversalFilters, ReplayTabs, SessionRecordingType } from '~/types'

import { RecordingsUniversalFilters } from '../filters/RecordingsUniversalFilters'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { SessionRecordingPreview } from './SessionRecordingPreview'
import {
    DEFAULT_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistSettings } from './SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'

function SortedBy({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const simpleSortingOptions: LemonSelectSection<RecordingOrder> = {
        options: [
            {
                value: 'start_time',
                label: 'Latest',
            },
            {
                value: 'activity_score',
                label: 'Activity',
            },
            {
                value: 'console_error_count',
                label: 'Most errors',
            },
        ],
    }
    const detailedSortingOptions: LemonSelectSection<RecordingOrder> = {
        options: [
            {
                label: 'Longest',
                options: [
                    {
                        value: 'duration',
                        label: 'Total duration',
                    },
                    {
                        value: 'active_seconds',
                        label: 'Active duration',
                    },
                    {
                        value: 'inactive_seconds',
                        label: 'Inactive duration',
                    },
                ],
            },
            {
                label: 'Most active',
                options: [
                    {
                        value: 'click_count',
                        label: 'Clicks',
                    },
                    {
                        value: 'keypress_count',
                        label: 'Key presses',
                    },
                    {
                        value: 'mouse_activity_count',
                        label: 'Mouse activity',
                    },
                ],
            },
        ],
    }
    return (
        <div className="px-2 py-1 justify-end flex flex-row gap-2 w-full items-center">
            <span className="font-medium">sorted by</span>
            <LemonSelect
                allowClear={false}
                options={[simpleSortingOptions, detailedSortingOptions]}
                size="xsmall"
                value={filters.order}
                onChange={(order) => setFilters({ order })}
            />
        </div>
    )
}

export function SessionRecordingsPlaylist(props: SessionRecordingPlaylistLogicProps): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
    }
    const logic = sessionRecordingsPlaylistLogic(logicProps)
    const {
        filters,
        pinnedRecordings,
        matchingEventsMatchType,
        sessionRecordingsResponseLoading,
        otherRecordings,
        activeSessionRecordingId,
        hasNext,
    } = useValues(logic)
    const { maybeLoadSessionRecordings, setSelectedRecordingId, setFilters, setShowOtherRecordings } = useActions(logic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'

    const pinnedDescription = isTestingSaved ? 'Saved' : 'Pinned'

    const notebookNode = useNotebookNode()

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
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className="h-full space-y-2">
                {!notebookNode && (
                    <RecordingsUniversalFilters filters={filters} setFilters={setFilters} className="border" />
                )}
                <Playlist
                    data-attr="session-recordings-playlist"
                    controls={filters && setFilters ? <SortedBy filters={filters} setFilters={setFilters} /> : null}
                    notebooksHref={urls.replay(ReplayTabs.Home, filters)}
                    title="Recordings"
                    embedded={!!notebookNode}
                    sections={sections}
                    onChangeSections={(activeSections) => setShowOtherRecordings(activeSections.includes('other'))}
                    headerActions={[
                        {
                            key: 'settings',
                            tooltip: 'Playlist settings',
                            content: <SessionRecordingsPlaylistSettings />,
                            icon: <IconGear />,
                        },
                    ]}
                    loading={sessionRecordingsResponseLoading}
                    onScrollListEdge={(edge) => {
                        if (edge === 'top') {
                            maybeLoadSessionRecordings('newer')
                        } else {
                            maybeLoadSessionRecordings('older')
                        }
                    }}
                    listEmptyState={<ListEmptyState />}
                    onSelect={(item) => setSelectedRecordingId(item.id)}
                    activeItemId={activeSessionRecordingId}
                    content={({ activeItem }) =>
                        activeItem ? (
                            <SessionRecordingPlayer
                                playerKey={props.logicKey ?? 'playlist'}
                                sessionRecordingId={activeItem.id}
                                matchingEventsMatchType={matchingEventsMatchType}
                                playlistLogic={logic}
                                noBorder
                                pinned={!!pinnedRecordings.find((x) => x.id === activeItem.id)}
                                setPinned={
                                    props.onPinnedChange
                                        ? (pinned) => {
                                              if (!activeItem.id) {
                                                  return
                                              }
                                              props.onPinnedChange?.(activeItem, pinned)
                                          }
                                        : undefined
                                }
                            />
                        ) : (
                            <div className="mt-20">
                                <EmptyMessage
                                    title="No recording selected"
                                    description="Please select a recording from the list on the left"
                                    buttonText="Learn more about recordings"
                                    buttonTo="https://posthog.com/docs/user-guides/recordings"
                                />
                            </div>
                        )
                    }
                />
            </div>
        </BindLogic>
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
                <Link to="https://posthog.com/docs/libraries/android" target="_blank">
                    the Android SDK
                </Link>
            </p>
        </LemonBanner>
    )
}
