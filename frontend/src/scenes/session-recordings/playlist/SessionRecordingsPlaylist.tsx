import { IconFilter, IconGear } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

import { RecordingsUniversalFilters } from '../filters/RecordingsUniversalFilters'
import { SessionRecordingPreview } from './SessionRecordingPreview'
import {
    DEFAULT_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistSettings } from './SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'
import { Playlist, PlaylistSection } from 'lib/components/Playlist/Playlist'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'

export function SessionRecordingsPlaylist(props: SessionRecordingPlaylistLogicProps): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
    }
    const logic = sessionRecordingsPlaylistLogic(logicProps)
    const {
        filters,
        pinnedRecordings,
        totalFiltersCount,
        useUniversalFiltering,
        matchingEventsMatchType,
        sessionRecordingsResponseLoading,
        otherRecordings,
        sessionSummaryLoading,
    } = useValues(logic)
    const { maybeLoadSessionRecordings, summarizeSession, setSelectedRecordingId } = useActions(logic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'

    const pinnedDescription = isTestingSaved ? 'Saved' : 'Pinned'

    const notebookNode = useNotebookNode()

    const sections: PlaylistSection[] = []
    const headerActions = []

    const onSummarizeClick = (recording: SessionRecordingType): void => {
        summarizeSession(recording.id)
    }

    if (!useUniversalFiltering || notebookNode) {
        headerActions.push({
            key: 'filters',
            tooltip: 'Filter recordings',
            content: <SessionRecordingsPlaylistSettings />,
            icon: (
                <IconWithCount count={totalFiltersCount}>
                    <IconFilter />
                </IconWithCount>
            ),
            children: 'Filter',
            // onClick={() => {
            //     if (notebookNode) {
            //         notebookNode.actions.toggleEditing()
            //     } else {
            //         setShowFilters(!showFilters)
            //     }
            // }}
        })
    }

    headerActions.push({
        key: 'settings',
        tooltip: 'Playlist settings',
        content: <SessionRecordingsPlaylistSettings />,
        icon: <IconGear />,
    })

    if (pinnedRecordings.length) {
        sections.push({
            title: `${pinnedDescription} recordings`,
            items: pinnedRecordings,
            render: ({ item, isActive }) => (
                <SessionRecordingPreview
                    recording={item}
                    // onClick={() => setSelectedRecordingId(rec.id)}
                    isActive={isActive}
                    pinned={true}
                />
            ),
        })
    }

    sections.push({
        title: pinnedRecordings.length ? 'Other recordings' : undefined,
        items: otherRecordings,
        collapsible: true,
        render: ({ item, isActive }) => (
            <SessionRecordingPreview
                recording={item}
                //   onClick={() => onRecordingClick(rec)}
                isActive={isActive}
                pinned={false}
                summariseFn={onSummarizeClick}
                sessionSummaryLoading={sessionSummaryLoading}
            />
        ),
    })

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className="h-full space-y-2">
                {useUniversalFiltering && <RecordingsUniversalFilters />}
                <Playlist
                    notebooksHref={urls.replay(ReplayTabs.Recent, filters)}
                    title={!notebookNode ? 'Recordings' : undefined}
                    embedded={!!notebookNode}
                    sections={sections}
                    headerActions={headerActions}
                    loading={sessionRecordingsResponseLoading}
                    onScrollListEdge={(edge) => {
                        if (edge === 'top') {
                            maybeLoadSessionRecordings('newer')
                        } else {
                            maybeLoadSessionRecordings('older')
                        }
                    }}
                    listEmptyState={<ListEmptyState />}
                    onSelect={setSelectedRecordingId}
                    content={({ activeItem }) => (
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
                    )}
                />
            </div>
        </BindLogic>
    )
}

const ListEmptyState = () => {
    const { filters, sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)
    const { setAdvancedFilters } = useActions(sessionRecordingsPlaylistLogic)

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
                                onClick={() => {
                                    setAdvancedFilters({
                                        date_from: '-30d',
                                    })
                                }}
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
