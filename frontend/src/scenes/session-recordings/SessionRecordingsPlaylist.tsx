import { useRef } from 'react'
import { useActions, useValues } from 'kea'
import { colonDelimitedDuration, range } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import {
    defaultPageviewPropertyEntityFilter,
    PLAYLIST_LIMIT,
    sessionRecordingsListLogic,
} from './sessionRecordingsListLogic'
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

interface SessionRecordingPlaylistItemProps {
    recording: SessionRecordingType
    isActive: boolean
    onClick: () => void
    onPropertyClick: (property: string, value?: string) => void
}

const SessionRecordingPlaylistItem = ({
    recording,
    isActive,
    onClick,
    onPropertyClick,
}: SessionRecordingPlaylistItemProps): JSX.Element => {
    const formattedDuration = colonDelimitedDuration(recording.recording_duration)
    const durationParts = formattedDuration.split(':')

    const { featureFlags } = useValues(featureFlagLogic)

    const listIcons = featureFlags[FEATURE_FLAGS.RECORDING_LIST_ICONS] || 'none'
    const iconClassnames = clsx(
        'SessionRecordingsPlaylist__list-item__property-icon text-base text-muted-alt',
        !isActive && 'opacity-75'
    )
    const iconPropertyKeys = ['$browser', '$device_type', '$os', '$geoip_country_code']
    const iconProperties = recording.properties || recording.person?.properties || {}

    const indicatorRight = listIcons === 'bottom' || listIcons === 'none' || listIcons === 'middle' || !listIcons

    const propertyIcons = (
        <div className="flex flex-row flex-nowrap shrink-0 gap-1">
            {iconPropertyKeys.map((property) => (
                <PropertyIcon
                    key={property}
                    onClick={onPropertyClick}
                    className={iconClassnames}
                    property={property}
                    value={iconProperties?.[property]}
                    tooltipTitle={(_, value) => (
                        <div className="text-center">
                            Click to filter for
                            <br />
                            <span className="font-medium">{value ?? 'N/A'}</span>
                        </div>
                    )}
                />
            ))}
        </div>
    )

    const duration = (
        <span className="flex items-center font-semibold">
            <IconSchedule className={iconClassnames} />
            <span>
                <span className={clsx(durationParts[0] === '00' && 'opacity-50 font-normal')}>{durationParts[0]}:</span>
                <span
                    className={clsx({
                        'opacity-50 font-normal': durationParts[0] === '00' && durationParts[1] === '00',
                    })}
                >
                    {durationParts[1]}:
                </span>
                {durationParts[2]}
            </span>
        </span>
    )

    return (
        <li
            key={recording.id}
            className={clsx(
                'SessionRecordingsPlaylist__list-item',
                'flex flex-row py-2 pr-4 pl-0 cursor-pointer relative overflow-hidden',
                isActive && 'bg-primary-highlight font-semibold',
                indicatorRight && 'pl-4'
            )}
            onClick={() => onClick()}
        >
            {!indicatorRight && (
                <div className="w-2 h-2 mx-2">
                    {!recording.viewed ? (
                        <Tooltip title={'Indicates the recording has not been watched yet'}>
                            <div
                                className="w-2 h-2 mt-2 rounded-full bg-primary-light"
                                aria-label="unwatched-recording-label"
                            />
                        </Tooltip>
                    ) : null}
                </div>
            )}
            <div className="grow">
                <div className="flex items-center justify-between">
                    <div className="truncate font-medium text-primary ph-no-capture">
                        {asDisplay(recording.person, 25)}
                    </div>

                    <div className="flex-1" />

                    {listIcons === 'top-right' && propertyIcons}
                    {listIcons === 'bottom-right' && duration}
                    {indicatorRight && !recording.viewed && (
                        <Tooltip title={'Indicates the recording has not been watched yet'}>
                            <div
                                className="w-2 h-2 rounded-full bg-primary-light"
                                aria-label="unwatched-recording-label"
                            />
                        </Tooltip>
                    )}
                </div>

                {listIcons === 'middle' && <div>{propertyIcons}</div>}

                <div className="flex items-center justify-between">
                    <TZLabel
                        className="overflow-hidden text-ellipsis"
                        time={recording.start_time}
                        formatDate="MMMM DD, YYYY"
                        formatTime="h:mm A"
                    />
                    <div className="flex items-center gap-2 flex-1 justify-end">
                        {listIcons === 'bottom' && propertyIcons}
                        {listIcons !== 'bottom-right' ? duration : propertyIcons}
                    </div>
                </div>
            </div>
        </li>
    )
}

export function SessionRecordingsPlaylist({ personUUID }: SessionRecordingsTableProps): JSX.Element {
    const logicProps = { personUUID }
    const logic = sessionRecordingsListLogic(logicProps)
    const {
        sessionRecordings,
        sessionRecordingsResponseLoading,
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
