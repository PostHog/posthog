import { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { range } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import {
    defaultPageviewPropertyEntityFilter,
    PLAYLIST_LIMIT,
    sessionRecordingsListLogic,
} from './sessionRecordingsListLogic'
import './SessionRecordingsPlaylist.scss'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft, IconChevronRight } from 'lib/components/icons'
import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import clsx from 'clsx'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { LemonTableLoader } from 'lib/components/LemonTable/LemonTableLoader'
import { SessionRecordingPlaylistItem } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistItem'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsPlaylist({ personUUID }: SessionRecordingsTableProps): JSX.Element {
    const logicProps = { personUUID }
    const logic = sessionRecordingsListLogic(logicProps)
    const {
        sessionRecordings,
        sessionRecordingIdToProperties,
        sessionRecordingsResponseLoading,
        sessionRecordingsPropertiesResponseLoading,
        hasNext,
        hasPrev,
        activeSessionRecording,
        offset,
        entityFilters,
    } = useValues(logic)
    const { setSelectedRecordingId, loadNext, loadPrev, setEntityFilters } = useActions(logic)
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

    const onPropertyClick = (property: string, value?: string): void => {
        setEntityFilters(defaultPageviewPropertyEntityFilter(entityFilters, property, value))
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
                                <>
                                    {i > 0 && <div className="border-t" />}
                                    <SessionRecordingPlaylistItem
                                        key={rec.id}
                                        recording={rec}
                                        recordingProperties={sessionRecordingIdToProperties[rec.id]}
                                        recordingPropertiesLoading={sessionRecordingsPropertiesResponseLoading}
                                        onClick={() => onRecordingClick(rec)}
                                        onPropertyClick={onPropertyClick}
                                        isActive={activeSessionRecording?.id === rec.id}
                                    />
                                </>
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
