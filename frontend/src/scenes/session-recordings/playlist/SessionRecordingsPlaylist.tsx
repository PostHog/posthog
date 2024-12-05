import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Playlist, PlaylistSection } from 'lib/components/Playlist/Playlist'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

import { RecordingsUniversalFilters } from '../filters/RecordingsUniversalFilters'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { SessionRecordingPreview } from './SessionRecordingPreview'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import {
    SessionRecordingPlaylistBottomSettings,
    SessionRecordingsPlaylistTopSettings,
} from './SessionRecordingsPlaylistSettings'

export function SessionRecordingsPlaylist({
    showContent = true,
    ...props
}: SessionRecordingPlaylistLogicProps & { showContent?: boolean }): JSX.Element {
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
    const allowReplayHogQLFilters = !!featureFlags[FEATURE_FLAGS.REPLAY_HOGQL_FILTERS]

    const pinnedDescription = isTestingSaved ? 'Saved' : 'Pinned'

    const { playlistOpen } = useValues(playerSettingsLogic)

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
                    <RecordingsUniversalFilters
                        filters={filters}
                        setFilters={setFilters}
                        className="border"
                        allowReplayHogQLFilters={allowReplayHogQLFilters}
                    />
                )}
                <Playlist
                    isCollapsed={!playlistOpen}
                    data-attr="session-recordings-playlist"
                    notebooksHref={urls.replay(ReplayTabs.Home, filters)}
                    title="Results"
                    embedded={!!notebookNode}
                    sections={sections}
                    onChangeSections={(activeSections) => setShowOtherRecordings(activeSections.includes('other'))}
                    headerActions={<SessionRecordingsPlaylistTopSettings filters={filters} setFilters={setFilters} />}
                    footerActions={<SessionRecordingPlaylistBottomSettings />}
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
                        showContent && activeItem ? (
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
