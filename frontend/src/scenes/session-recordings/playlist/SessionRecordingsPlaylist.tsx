import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useRef } from 'react'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { cn } from 'lib/utils/css-classes'
import { Playlist } from 'scenes/session-recordings/playlist/Playlist'

import { RecordingsUniversalFiltersEmbed } from '../filters/RecordingsUniversalFiltersEmbed'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylist({
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

    const playlistRef = useRef<HTMLDivElement>(null)
    const { isCinemaMode } = useValues(playerSettingsLogic)
    const { isWindowLessThan } = useWindowSize()
    const isVerticalLayout = isWindowLessThan('xl')

    const logicKey = `playlist-resizer-${isVerticalLayout ? 'vertical' : 'horizontal'}`
    const resizerLogicProps: ResizerLogicProps = {
        logicKey,
        containerRef: playlistRef,
        persistent: true,
        placement: isVerticalLayout ? 'top' : 'right',
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div
                className={clsx('w-full h-full', {
                    'flex flex-col gap-2 xl:flex-row': !isCinemaMode,
                })}
            >
                <div
                    ref={playlistRef}
                    className={clsx('relative flex flex-col shrink-0', {
                        'order-last xl:order-first': !isCinemaMode,
                        'w-0': isCinemaMode,
                    })}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={
                        isCinemaMode
                            ? {}
                            : isVerticalLayout
                              ? { height: desiredSize ?? undefined, minHeight: 200 }
                              : { width: desiredSize ?? 320, minWidth: 200, maxWidth: '50%' }
                    }
                >
                    <Playlist {...props} />
                    {!isCinemaMode && (
                        <Resizer
                            {...resizerLogicProps}
                            visible={false}
                            offset={-4} // push into the center of the gap
                            handleClassName={cn('rounded', isVerticalLayout ? 'mx-1' : 'my-1')}
                        />
                    )}
                </div>

                <PlayerWrapper {...props} />
            </div>
        </BindLogic>
    )
}

function PlayerWrapper({
    showContent = true,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
}): JSX.Element {
    const {
        filters,
        pinnedRecordings,
        matchingEventsMatchType,
        activeSessionRecording,
        allowHogQLFilters,
        totalFiltersCount,
        nextSessionRecording,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters, setSelectedRecordingId } = useActions(sessionRecordingsPlaylistLogic)

    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { isCinemaMode } = useValues(playerSettingsLogic)

    const onPlayNextRecording = useCallback(() => {
        if (nextSessionRecording?.id) {
            setSelectedRecordingId(nextSessionRecording.id)
        }
    }, [nextSessionRecording, setSelectedRecordingId])

    return (
        <div
            className={clsx('Playlist__main overflow-hidden shrink-0 xl:shrink h-full flex-1 rounded border', {
                'w-full': isCinemaMode,
                'min-h-96': !isCinemaMode,
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
                        sessionRecordingsPlaylistLogic.actions.loadAllRecordings()
                        sessionRecordingsPlaylistLogic.actions.setSelectedRecordingId(null)
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
    )
}
