import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Playlist } from 'scenes/session-recordings/playlist/Playlist'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { RecordingsUniversalFiltersEmbed } from '../filters/RecordingsUniversalFiltersEmbed'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { PlaylistPopoverButton } from '../player/playlist-popover/PlaylistPopover'
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

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div
                className={clsx('w-full h-full', {
                    'flex flex-col xl:flex-row gap-2 overflow-y-auto xl:overflow-hidden': !isCinemaMode,
                })}
            >
                <div
                    className={clsx('flex flex-col overflow-hidden shrink-0 xl:shrink', {
                        'xl:w-1/4 xl:min-w-80 order-last xl:order-first': !isCinemaMode,
                        'w-0': isCinemaMode,
                    })}
                >
                    <Playlist {...props} />
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
        activeSessionRecording,
        allowHogQLFilters,
        totalFiltersCount,
        nextSessionRecording,
        pinnedRecordings,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters, setSelectedRecordingId } = useActions(sessionRecordingsPlaylistLogic)

    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { isCinemaMode } = useValues(playerSettingsLogic)

    const onPlayNextRecording = useCallback(() => {
        if (nextSessionRecording?.id) {
            setSelectedRecordingId(nextSessionRecording.id)
        }
    }, [nextSessionRecording, setSelectedRecordingId])

    const isInCollection = useMemo(() => {
        return pinnedRecordings.some((r) => r.id === activeSessionRecording?.id)
    }, [pinnedRecordings, activeSessionRecording?.id])

    const collectionButton = useMemo(() => {
        if (!props.onPinnedChange || !activeSessionRecording) {
            return null
        }
        const tooltip = isInCollection ? 'Remove from collection' : 'Add to collection'
        return (
            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <PlaylistPopoverButton
                    tooltip={tooltip}
                    setPinnedInCurrentPlaylist={() => props.onPinnedChange?.(activeSessionRecording, !isInCollection)}
                    icon={isInCollection ? <IconMinusSmall /> : <IconPlusSmall />}
                    size="xsmall"
                >
                    {tooltip}
                </PlaylistPopoverButton>
            </AccessControlAction>
        )
    }, [activeSessionRecording, isInCollection, props])

    return (
        <div
            className={clsx('Playlist__main overflow-hidden shrink-0 xl:shrink', {
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
                    onRecordingDeleted={() => {
                        sessionRecordingsPlaylistLogic.actions.loadAllRecordings()
                        sessionRecordingsPlaylistLogic.actions.setSelectedRecordingId(null)
                    }}
                    noBorder
                    playNextRecording={onPlayNextRecording}
                    metaControls={collectionButton}
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
