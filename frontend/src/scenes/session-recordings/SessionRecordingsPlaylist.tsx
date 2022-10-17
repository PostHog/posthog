import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { colonDelimitedDuration, range } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { PLAYLIST_LIMIT, sessionRecordingsListLogic } from './sessionRecordingsListLogic'
import { asDisplay } from 'scenes/persons/PersonHeader'
import './SessionRecordingsPlaylist.scss'
import { TZLabel } from 'lib/components/TimezoneAware'
import { SessionRecordingPlayer } from './player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft, IconChevronRight, IconSchedule } from 'lib/components/icons'
import { SessionRecordingsFilters } from './filters/SessionRecordingsFilters'
import clsx from 'clsx'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { LemonTableLoader } from 'lib/components/LemonTable/LemonTableLoader'

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
                <span className={clsx(parts[0] === '00' && 'opacity-50')}>{parts[0]}:</span>
                <span
                    className={clsx({
                        'opacity-50': parts[0] === '00' && parts[1] === '00',
                    })}
                >
                    {parts[1]}:
                </span>
                {parts[2]}
            </span>
        </span>
    )
}

export function SessionRecordingsPlaylist({ personUUID }: SessionRecordingsTableProps): JSX.Element {
    const logic = sessionRecordingsListLogic({ personUUID })
    const { sessionRecordings, sessionRecordingsResponseLoading, hasNext, hasPrev, activeSessionRecording, offset } =
        useValues(logic)
    const { setSelectedRecordingId, loadNext, loadPrev } = useActions(logic)
    const playlistRef = useRef<HTMLDivElement>(null)

    const onRecordingClick = (recording: SessionRecordingType): void => {
        setSelectedRecordingId(recording.id)

        const scrollToTop = playlistRef?.current?.offsetTop ? playlistRef.current.offsetTop - 8 : 0

        if (window.scrollY > scrollToTop) {
            window.scrollTo({
                left: 0,
                top: scrollToTop,
                behavior: 'smooth',
            })
        }
    }

    const nextLength = offset + (sessionRecordingsResponseLoading ? PLAYLIST_LIMIT : sessionRecordings.length)

    const paginationControls = nextLength ? (
        <div className="flex items-center gap-1">
            <span>{`${offset + 1} - ${nextLength}`}</span>
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
    ) : null

    return (
        <div ref={playlistRef} className="SessionRecordingsPlaylist" data-attr="session-recordings-playlist">
            <div className="SessionRecordingsPlaylist__left-column space-y-4">
                <SessionRecordingsFilters personUUID={personUUID} />

                <div className="w-full overflow-hidden border rounded">
                    <div className="relative flex justify-between items-center bg-mid py-3 px-4 border-b">
                        <span className="font-bold uppercase text-xs my-1 tracking-wide">Recent Recordings</span>
                        {paginationControls}

                        <LemonTableLoader loading={sessionRecordingsResponseLoading} />
                    </div>

                    {!sessionRecordings.length ? (
                        sessionRecordingsResponseLoading ? (
                            <>
                                {range(PLAYLIST_LIMIT).map((i) => (
                                    <div key={i} className="p-4 space-y-2 border-b">
                                        <LemonSkeleton className="w-1/2" />
                                        <LemonSkeleton className="w-1/3" />
                                    </div>
                                ))}
                            </>
                        ) : (
                            <p className="text-muted-alt m-4">No matching recordings found</p>
                        )
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
                                        <div className="truncate font-medium text-primary ph-no-capture">
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

                <div className="flex justify-between items-center">
                    <LemonButton
                        icon={<IconChevronLeft />}
                        type="secondary"
                        disabled={!hasPrev}
                        onClick={() => {
                            loadPrev()
                            window.scrollTo(0, 0)
                        }}
                    >
                        Previous
                    </LemonButton>

                    <span>{`${offset + 1} - ${nextLength}`}</span>

                    <LemonButton
                        icon={<IconChevronRight />}
                        type="secondary"
                        disabled={!hasNext}
                        onClick={() => {
                            loadNext()
                            window.scrollTo(0, 0)
                        }}
                    >
                        Next
                    </LemonButton>
                </div>
            </div>
            <div className="SessionRecordingsPlaylist__right-column">
                {activeSessionRecording?.id ? (
                    <div className="border rounded h-full">
                        <SessionRecordingPlayer
                            playerKey="playlist"
                            sessionRecordingId={activeSessionRecording?.id}
                            matching={activeSessionRecording?.matching_events}
                            recordingStartTime={activeSessionRecording ? activeSessionRecording.start_time : undefined}
                        />
                    </div>
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
    )
}
