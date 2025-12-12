import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Playlist } from 'scenes/session-recordings/playlist/Playlist'

import { RecordingsUniversalFiltersEmbed } from '../filters/RecordingsUniversalFiltersEmbed'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylist({
    showContent = true,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
}): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
    }
    const playlistLogic = sessionRecordingsPlaylistLogic(logicProps)
    const {
        filters,
        pinnedRecordings,
        matchingEventsMatchType,
        activeSessionRecording,
        allowHogQLFilters,
        totalFiltersCount,
        nextSessionRecording,
    } = useValues(playlistLogic)
    const { setFilters, resetFilters, setSelectedRecordingId } = useActions(playlistLogic)

    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { isCinemaMode } = useValues(playerSettingsLogic)

    const onPlayNextRecording = useCallback(() => {
        if (nextSessionRecording?.id) {
            setSelectedRecordingId(nextSessionRecording.id)
        }
    }, [nextSessionRecording, setSelectedRecordingId])

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div
                className={clsx('w-full h-full', {
                    'flex flex-col xl:flex-row gap-2': !isCinemaMode,
                })}
            >
                <div
                    className={clsx('flex flex-col', {
                        'xl:w-1/4 xl:min-w-80 order-last xl:order-first': !isCinemaMode,
                        'w-0 overflow-hidden': isCinemaMode,
                    })}
                >
                    <Playlist {...props} />
                </div>

                <div
                    className={clsx('Playlist__main overflow-hidden', {
                        'w-full': isCinemaMode,
                        'xl:flex-1 xl:h-full min-h-96 xl:rounded xl:border-y xl:border-r border-l xl:border-l-0 rounded-bl':
                            !isCinemaMode,
                    })}
                >
                    {isFiltersExpanded ? (
                        <RecordingsUniversalFiltersEmbed
                            resetFilters={resetFilters}
                            filters={filters}
                            setFilters={setFilters}
                            totalFiltersCount={totalFiltersCount}
                            allowReplayHogQLFilters={allowHogQLFilters}
                        />
                    ) : showContent && activeSessionRecording ? (
                        <SessionRecordingPlayer
                            playerKey={props.logicKey ?? 'playlist'}
                            sessionRecordingId={activeSessionRecording.id}
                            matchingEventsMatchType={matchingEventsMatchType}
                            onRecordingDeleted={() => {
                                playlistLogic.actions.loadAllRecordings()
                                playlistLogic.actions.setSelectedRecordingId(null)
                            }}
                            noBorder
                            pinned={!!pinnedRecordings.find((x) => x.id === activeSessionRecording.id)}
                            setPinned={
                                props.onPinnedChange
                                    ? (pinned) => {
                                          if (!activeSessionRecording.id) {
                                              return
                                          }
                                          props.onPinnedChange?.(activeSessionRecording, pinned)
                                      }
                                    : undefined
                            }
                            playNextRecording={onPlayNextRecording}
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
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
