import { useRef } from 'react'
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
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

const SessionRecordingPlaylistItem = ({
    recording,
    isActive,
    onClick,
}: {
    recording: SessionRecordingType
    isActive: boolean
    onClick: () => void
}): JSX.Element => {
    const iconClassnames = isActive ? 'text-lg text-muted-alt' : 'text-lg text-muted-alt opacity-75'
    const formattedDuration = colonDelimitedDuration(recording.recording_duration)
    const durationParts = formattedDuration.split(':')

    const { featureFlags } = useValues(featureFlagLogic)

    const listIcons = featureFlags[FEATURE_FLAGS.RECORDING_LIST_ICONS] || 'none'

    const propertyIcons = (
        <div className="flex flex-row flex-nowrap shrink-0 gap-1">
            <PropertyIcon className={iconClassnames} property="$browser" value={recording.properties?.['$browser']} />
            <PropertyIcon
                className={iconClassnames}
                property="$device_type"
                value={recording.properties?.['$device_type']}
            />
            <PropertyIcon className={iconClassnames} property="$os" value={recording.properties?.['$os']} />
            <PropertyIcon
                className={iconClassnames}
                property="$geoip_country_code"
                value={recording.properties?.['$geoip_country_code']}
            />
        </div>
    )

    return (
        <li
            key={recording.id}
            className={clsx(
                'SessionRecordingsPlaylist__list-item',
                'p-2 px-4 cursor-pointer relative overflow-hidden',
                isActive && 'bg-primary-highlight font-semibold',
                !recording.viewed && listIcons !== 'none' && 'SessionRecordingsPlaylist__list-item--unwatched'
            )}
            onClick={() => onClick()}
        >
            <div className="flex justify-between items-center">
                <div className="truncate font-medium text-primary ph-no-capture">{asDisplay(recording.person, 25)}</div>

                {listIcons === 'top' && propertyIcons}
                {!recording.viewed && (
                    <>
                        {listIcons === 'none' ? (
                            <Tooltip title={'Indicates the recording has not been watched yet'}>
                                <div
                                    className="w-2 h-2 rounded bg-primary-light"
                                    aria-label="unwatched-recording-label"
                                />
                            </Tooltip>
                        ) : (
                            <Tooltip title={'Indicates the recording has not been watched yet'}>
                                <div
                                    className="absolute top-0 right-0 w-3 h-3 bg-transparent z-10"
                                    aria-label="unwatched-recording-label"
                                />
                            </Tooltip>
                        )}
                    </>
                )}
            </div>

            <div className="flex justify-between items-center">
                <TZLabel time={recording.start_time} formatDate="MMMM DD, YYYY" formatTime="h:mm A" />
                <div className="flex items-center gap-2">
                    {listIcons === 'bottom' && propertyIcons}
                    <span className="flex items-center font-normal">
                        <IconSchedule className={iconClassnames} />
                        <span>
                            <span className={clsx(durationParts[0] === '00' && 'opacity-50')}>{durationParts[0]}:</span>
                            <span
                                className={clsx({
                                    'opacity-50': durationParts[0] === '00' && durationParts[1] === '00',
                                })}
                            >
                                {durationParts[1]}:
                            </span>
                            {durationParts[2]}
                        </span>
                    </span>
                </div>
            </div>
        </li>
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
                                <>
                                    {i > 0 && <div className="border-t" />}
                                    <SessionRecordingPlaylistItem
                                        key={rec.id}
                                        recording={rec}
                                        onClick={() => onRecordingClick(rec)}
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
