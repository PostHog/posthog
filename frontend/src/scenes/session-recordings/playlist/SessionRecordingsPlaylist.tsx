import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useRef } from 'react'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'
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

    const { isCinemaMode } = useValues(playerSettingsLogic)
    const { isWindowLessThan } = useWindowSize()
    const isVerticalLayout = isWindowLessThan('xl')

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className="w-full h-full flex flex-col xl:flex-row xl:gap-2">
                {isVerticalLayout ? (
                    <VerticalLayout {...props} isCinemaMode={isCinemaMode} />
                ) : (
                    <HorizontalLayout {...props} isCinemaMode={isCinemaMode} />
                )}
            </div>
        </BindLogic>
    )
}

function HorizontalLayout({
    isCinemaMode,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
    isCinemaMode: boolean
}): JSX.Element {
    const playlistRef = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'playlist-resizer-horizontal',
        containerRef: playlistRef,
        persistent: true,
        persistPrefix: '2025-12-29',
        placement: 'right',
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <div
                ref={playlistRef}
                className={clsx('relative flex flex-col shrink-0', {
                    'w-0 overflow-hidden': isCinemaMode,
                })}
                // eslint-disable-next-line react/forbid-dom-props
                style={isCinemaMode ? {} : { width: desiredSize ?? 320, minWidth: 200, maxWidth: '50%' }}
            >
                <Playlist {...props} />
                {!isCinemaMode && (
                    <Resizer {...resizerLogicProps} visible={false} offset={-4} handleClassName="rounded my-1" />
                )}
            </div>
            <PlayerWrapper {...props} className="h-full flex-1 shrink" />
        </>
    )
}

function VerticalLayout({
    isCinemaMode,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
    isCinemaMode: boolean
}): JSX.Element {
    const playerRef = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'playlist-resizer-vertical',
        containerRef: playerRef,
        persistent: true,
        persistPrefix: '2025-12-29',
        placement: 'bottom',
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <PlayerWrapper
                {...props}
                containerRef={playerRef}
                style={isCinemaMode ? {} : { height: desiredSize ?? undefined, minHeight: 300 }}
                className={isCinemaMode ? 'flex-1' : 'pb-2 shrink-0'}
                resizer={
                    !isCinemaMode ? (
                        <Resizer
                            {...resizerLogicProps}
                            visible={false}
                            offset="0.25rem"
                            handleClassName="rounded mx-1"
                        />
                    ) : null
                }
            />
            <div className={clsx('relative flex flex-col min-h-0', isCinemaMode ? 'h-0 overflow-hidden' : 'flex-1')}>
                <Playlist {...props} />
            </div>
        </>
    )
}

function PlayerWrapper({
    showContent = true,
    containerRef,
    style,
    resizer,
    className,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
    containerRef?: React.RefObject<HTMLDivElement>
    style?: React.CSSProperties
    resizer?: React.ReactNode
    className?: string
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
            ref={containerRef}
            className={clsx('Playlist__main relative overflow-hidden', className, {
                'w-full': isCinemaMode,
                'min-h-96': !isCinemaMode,
            })}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
        >
            {isFiltersExpanded ? (
                <div className="h-full rounded border">
                    <RecordingsUniversalFiltersEmbed
                        resetFilters={resetFilters}
                        filters={filters}
                        setFilters={setFilters}
                        totalFiltersCount={totalFiltersCount}
                        allowReplayHogQLFilters={allowHogQLFilters}
                    />
                </div>
            ) : showContent && activeSessionRecording ? (
                <SessionRecordingPlayer
                    playerKey={props.logicKey ?? 'playlist'}
                    sessionRecordingId={activeSessionRecording.id}
                    matchingEventsMatchType={matchingEventsMatchType}
                    onRecordingDeleted={() => {
                        sessionRecordingsPlaylistLogic.actions.loadAllRecordings()
                        sessionRecordingsPlaylistLogic.actions.setSelectedRecordingId(null)
                    }}
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
            {resizer}
        </div>
    )
}
