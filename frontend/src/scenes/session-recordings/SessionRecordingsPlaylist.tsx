import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { colonDelimitedDuration } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { getRecordingListLimit, PLAYLIST_LIMIT, sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { asDisplay } from 'scenes/persons/PersonHeader'
import './SessionRecordingsPlaylist.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { SessionRecordingPlayerV3 } from './player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { IconAutocapture, IconChevronLeft, IconChevronRight, IconKeyboard } from 'lib/components/icons'
import { SessionRecordingsFilters } from './filters/SessionRecordingsFilters'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsPlaylist({ personUUID }: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID, isPlaylist: true })
    const { sessionRecordings, sessionRecordingsResponseLoading, hasNext, hasPrev, activeSessionRecordingId, offset } =
        useValues(sessionRecordingsTableLogicInstance)
    const { openSessionPlayer, loadNext, loadPrev } = useActions(sessionRecordingsTableLogicInstance)
    const playlistRef = useRef<HTMLDivElement>(null)

    const columns: LemonTableColumns<SessionRecordingType> = [
        {
            title: 'Recordings',
            render: function RenderPlayButton(_: any, sessionRecording: SessionRecordingType) {
                return (
                    <div className="flex flex-col gap-2">
                        <div className="text-primary">{asDisplay(sessionRecording.person, 25)}</div>
                        <div className="flex gap-1">
                            <div className="flex items-center gap-1 rounded bg-primary-highlight p-1 text-xs">
                                <IconAutocapture /> {sessionRecording.click_count || 0} clicks
                            </div>
                            <div className="flex items-center gap-1 rounded bg-primary-highlight p-1 text-xs">
                                <IconKeyboard />
                                {sessionRecording.keypress_count || 0} inputs
                            </div>
                        </div>
                        <div>
                            <span className="text-xs flex justify-between">
                                <TZLabel
                                    time={sessionRecording.start_time}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="h:mm A"
                                />
                                {colonDelimitedDuration(sessionRecording.recording_duration)}
                            </span>
                        </div>
                    </div>
                )
            },
        },
    ]
    return (
        <div ref={playlistRef} className="SessionRecordingsPlaylist" data-attr="session-recordings-playlist">
            <div className="SessionRecordingsPlaylist__left-column space-y-4">
                <SessionRecordingsFilters personUUID={personUUID} />
                <LemonTable
                    dataSource={sessionRecordings}
                    columns={columns}
                    loading={sessionRecordingsResponseLoading}
                    onRow={(sessionRecording) => ({
                        onClick: (e) => {
                            // Lets the link to the person open the person's page and not the session recording
                            if (!(e.target as HTMLElement).closest('a')) {
                                openSessionPlayer(sessionRecording.id)
                                window.scrollTo({
                                    left: 0,
                                    top: playlistRef?.current?.offsetTop ? playlistRef.current.offsetTop - 8 : 0,
                                    behavior: 'smooth',
                                })
                            }
                        },
                    })}
                    rowStatus={(recording) => (activeSessionRecordingId === recording.id ? 'highlighted' : null)}
                    rowClassName="cursor-pointer"
                    data-attr="session-recording-table"
                    data-tooltip="session-recording-table"
                    emptyState="No matching recordings found"
                    loadingSkeletonRows={PLAYLIST_LIMIT}
                />
                <div className="flex justify-end items-center my-2">
                    <span>{`${offset + 1} - ${
                        offset +
                        (sessionRecordingsResponseLoading ? getRecordingListLimit(true) : sessionRecordings.length)
                    }`}</span>
                    <LemonButton
                        icon={<IconChevronLeft />}
                        status="stealth"
                        disabled={!hasPrev}
                        onClick={() => {
                            loadPrev()
                            window.scrollTo(0, 0)
                        }}
                    />
                    <LemonButton
                        icon={<IconChevronRight />}
                        status="stealth"
                        disabled={!hasNext}
                        onClick={() => {
                            loadNext()
                            window.scrollTo(0, 0)
                        }}
                    />
                </div>
            </div>
            <div className="SessionRecordingsPlaylist__right-column">
                {activeSessionRecordingId ? (
                    <div className="border rounded h-full">
                        <SessionRecordingPlayerV3 playerKey="playlist" sessionRecordingId={activeSessionRecordingId} />
                    </div>
                ) : (
                    <EmptyMessage
                        title="No recording selected"
                        description="Please select a recording from the list on the left"
                        buttonText="Learn more about recordings"
                        buttonTo="https://posthog.com/docs/user-guides/recordings"
                    />
                )}
            </div>
        </div>
    )
}
