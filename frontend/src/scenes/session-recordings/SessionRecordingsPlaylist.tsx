import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { colonDelimitedDuration, range } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { getRecordingListLimit, PLAYLIST_LIMIT, sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { asDisplay } from 'scenes/persons/PersonHeader'
import './SessionRecordingsPlaylist.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { SessionRecordingPlayerV3 } from './player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft, IconChevronRight, IconSchedule } from 'lib/components/icons'
import { SessionRecordingsFilters } from './filters/SessionRecordingsFilters'
import clsx from 'clsx'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

const DurationDisplay = ({ duration }: { duration: number }): JSX.Element => {
    const formattedDuration = colonDelimitedDuration(duration)
    const parts = formattedDuration.split(':')

    return (
        <span className="flex items-center gap-1">
            <IconSchedule className="text-lg" />
            <span>
                <span className={parts[0] === '00' ? 'opacity-50' : ''}>{parts[0]}:</span>
                <span className={parts[0] === '00' && parts[1] === '00' ? 'opacity-50' : ''}>{parts[1]}:</span>
                {parts[2]}
            </span>
        </span>
    )
}

export function SessionRecordingsPlaylist({ personUUID }: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID, isPlaylist: true })
    const { sessionRecordings, sessionRecordingsResponseLoading, hasNext, hasPrev, activeSessionRecording, offset } =
        useValues(sessionRecordingsTableLogicInstance)
    const { openSessionPlayer, loadNext, loadPrev } = useActions(sessionRecordingsTableLogicInstance)
    const playlistRef = useRef<HTMLDivElement>(null)

    const onRecordingClick = (recording: SessionRecordingType): void => {
        openSessionPlayer({ id: recording.id })
        window.scrollTo({
            left: 0,
            top: playlistRef?.current?.offsetTop ? playlistRef.current.offsetTop - 8 : 0,
            behavior: 'smooth',
        })
    }

    const paginationControls = (
        <div className="flex items-center gap-1">
            <span>{`${offset + 1} - ${
                offset + (sessionRecordingsResponseLoading ? getRecordingListLimit(true) : sessionRecordings.length)
            }`}</span>
            <LemonButton
                icon={<IconChevronLeft />}
                status="stealth"
                size="small"
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
                size="small"
                onClick={() => {
                    loadNext()
                    window.scrollTo(0, 0)
                }}
            />
        </div>
    )

    return (
        <div ref={playlistRef} className="SessionRecordingsPlaylist" data-attr="session-recordings-playlist">
            <div className="SessionRecordingsPlaylist__left-column space-y-4">
                <SessionRecordingsFilters personUUID={personUUID} />

                <div className="w-full overflow-hidden border rounded">
                    <div className="flex justify-between items-center bg-mid py-3 px-4 border-b">
                        <span className="font-bold uppercase text-xs">Recent Recordings</span>
                        {paginationControls}
                    </div>
                    {sessionRecordingsResponseLoading && !sessionRecordings.length ? (
                        <>
                            {range(10).map((i) => (
                                <div key={i} className="p-4 space-y-2 border-b">
                                    <LemonSkeleton className="w-1/2" />
                                    <LemonSkeleton className="w-1/3" />
                                </div>
                            ))}
                        </>
                    ) : (
                        <ul className={clsx(sessionRecordingsResponseLoading ? 'opacity-50' : '')}>
                            {sessionRecordings.map((rec, i) => (
                                <li
                                    key={rec.id}
                                    className={clsx(
                                        'p-2 px-4 cursor-pointer',
                                        activeSessionRecording?.id === rec.id
                                            ? 'bg-primary-highlight font-semibold'
                                            : '',
                                        i !== 0 && 'border-t'
                                    )}
                                    onClick={() => onRecordingClick(rec)}
                                >
                                    <div className="flex justify-between items-center">
                                        <div className="truncate font-medium text-primary">
                                            {asDisplay(rec.person, 25)}
                                        </div>
                                        {!rec.viewed && (
                                            <Tooltip title={'Indicates the recording has not been watched yet'}>
                                                <div
                                                    className="w-2 h-2 rounded bg-primary-light"
                                                    aria-label="unwatched-recording-label"
                                                />
                                            </Tooltip>
                                        )}
                                    </div>

                                    <div className="flex justify-between">
                                        <TZLabel time={rec.start_time} formatDate="MMMM DD, YYYY" formatTime="h:mm A" />
                                        <DurationDisplay duration={rec.recording_duration} />
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                {/* <LemonTable
                    dataSource={sessionRecordings}
                    columns={columns}
                    loading={sessionRecordingsResponseLoading}
                    onRow={(sessionRecording) => ({
                        onClick: (e) => {
                            // Lets the link to the person open the person's page and not the session recording
                            if (!(e.target as HTMLElement).closest('a')) {
                                openSessionPlayer({ id: sessionRecording.id })
                                window.scrollTo({
                                    left: 0,
                                    top: playlistRef?.current?.offsetTop ? playlistRef.current.offsetTop - 8 : 0,
                                    behavior: 'smooth',
                                })
                            }
                        },
                    })}
                    rowStatus={(recording) => (activeSessionRecording?.id === recording.id ? 'highlighted' : null)}
                    rowClassName="cursor-pointer"
                    data-attr="session-recording-table"
                    data-tooltip="session-recording-table"
                    emptyState="No matching recordings found"
                    loadingSkeletonRows={PLAYLIST_LIMIT}
                /> */}
                <div className="flex justify-end my-2">{paginationControls}</div>
            </div>
            <div className="SessionRecordingsPlaylist__right-column">
                {activeSessionRecording?.id ? (
                    <div className="border rounded h-full">
                        <SessionRecordingPlayerV3
                            playerKey="playlist"
                            sessionRecordingId={activeSessionRecording.id}
                            matching={activeSessionRecording?.matching_events}
                            recordingStartTime={activeSessionRecording ? activeSessionRecording.start_time : undefined}
                        />
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
