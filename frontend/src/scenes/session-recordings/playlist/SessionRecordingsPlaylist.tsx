import { Fragment, useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { range } from '~/lib/utils'
import { RecordingDurationFilter, RecordingFilters, SessionRecordingType } from '~/types'
import {
    defaultPageviewPropertyEntityFilter,
    PLAYLIST_LIMIT,
    sessionRecordingsListLogic,
} from './sessionRecordingsListLogic'
import './SessionRecordingsPlaylist.scss'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import {
    IconChevronLeft,
    IconChevronRight,
    IconFilter,
    IconInfo,
    IconUnfoldLess,
    IconWithCount,
} from 'lib/components/icons'
import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import clsx from 'clsx'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { LemonTableLoader } from 'lib/components/LemonTable/LemonTableLoader'
import { SessionRecordingPlaylistItem } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistItem'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { DurationFilter } from '../filters/DurationFilter'
import { Tooltip } from 'lib/components/Tooltip'

export type SessionRecordingsPlaylistProps = {
    playlistShortId?: string
    personUUID?: string
    filters?: RecordingFilters
    updateSearchParams?: boolean
    onFiltersChange?: (filters: RecordingFilters) => void
}

export function SessionRecordingsPlaylist({
    playlistShortId,
    personUUID,
    filters: defaultFilters,
    updateSearchParams,
    onFiltersChange,
}: SessionRecordingsPlaylistProps): JSX.Element {
    const logic = sessionRecordingsListLogic({
        playlistShortId,
        personUUID,
        filters: defaultFilters,
        updateSearchParams,
    })
    const {
        sessionRecordings,
        sessionRecordingIdToProperties,
        sessionRecordingsResponseLoading,
        sessionRecordingsPropertiesResponseLoading,
        hasNext,
        hasPrev,
        activeSessionRecording,
        nextSessionRecording,
        filters,
        totalFiltersCount,
        showFilters,
        pinnedRecordingsResponse,
        pinnedRecordingsResponseLoading,
    } = useValues(logic)
    const { setSelectedRecordingId, loadNext, loadPrev, setFilters, reportRecordingsListFilterAdded, setShowFilters } =
        useActions(logic)
    const playlistRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (filters !== defaultFilters) {
            onFiltersChange?.(filters)
        }
    }, [filters])

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
        setFilters(defaultPageviewPropertyEntityFilter(filters, property, value))
    }

    const offset = filters.offset ?? 0
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
        <>
            <div className="flex flex-wrap items-end justify-between gap-4 mb-4">
                <div className="flex items-center gap-4">
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={
                                <IconWithCount count={totalFiltersCount}>
                                    <IconFilter />
                                </IconWithCount>
                            }
                            onClick={() => {
                                setShowFilters(!showFilters)
                                if (personUUID) {
                                    const entityFilterButtons = document.querySelectorAll('.entity-filter-row button')
                                    if (entityFilterButtons.length > 0) {
                                        ;(entityFilterButtons[0] as HTMLElement).click()
                                    }
                                }
                            }}
                        >
                            {showFilters ? 'Hide filters' : 'Filters'}
                        </LemonButton>

                        <LemonButton
                            type="secondary"
                            size="small"
                            disabled={!totalFiltersCount}
                            onClick={() => {
                                // saveNewPlaylist()
                            }}
                            // loading={newPlaylistLoading}
                            data-attr="save-recordings-playlist-button"
                            tooltip="Save the current filters as a playlist that you can come back to."
                        >
                            {playlistShortId ? 'Save changes' : 'Save as playlist'}
                        </LemonButton>
                    </>
                </div>

                <div className="flex items-center gap-4">
                    <DateFilter
                        dateFrom={filters.date_from ?? '-7d'}
                        dateTo={filters.date_to ?? undefined}
                        onChange={(changedDateFrom, changedDateTo) => {
                            reportRecordingsListFilterAdded(SessionRecordingFilterType.DateRange)
                            setFilters({
                                date_from: changedDateFrom,
                                date_to: changedDateTo,
                            })
                        }}
                        dateOptions={[
                            { key: 'Custom', values: [] },
                            { key: 'Last 24 hours', values: ['-24h'] },
                            { key: 'Last 7 days', values: ['-7d'] },
                            { key: 'Last 21 days', values: ['-21d'] },
                        ]}
                    />
                    <div className="flex gap-2">
                        <LemonLabel>Duration</LemonLabel>
                        <DurationFilter
                            onChange={(newFilter) => {
                                reportRecordingsListFilterAdded(SessionRecordingFilterType.Duration)
                                setFilters({ session_recording_duration: newFilter })
                            }}
                            initialFilter={filters.session_recording_duration as RecordingDurationFilter}
                            pageKey={!!personUUID ? `person-${personUUID}` : 'session-recordings'}
                        />
                    </div>
                </div>
            </div>
            <div ref={playlistRef} className="SessionRecordingsPlaylist" data-attr="session-recordings-playlist">
                <div className="SessionRecordingsPlaylist__left-column space-y-4">
                    {showFilters ? (
                        <SessionRecordingsFilters
                            filters={filters}
                            setFilters={setFilters}
                            showPropertyFilters={!personUUID}
                        />
                    ) : null}

                    {/* Pinned recordings */}

                    {!!playlistShortId &&
                        (pinnedRecordingsResponse?.results?.length ? (
                            <>
                                <div className="w-full overflow-hidden border rounded">
                                    <div className="relative flex justify-between items-center p-2 border-b gap-1">
                                        {playlistShortId ? (
                                            <LemonButton status="stealth" icon={<IconUnfoldLess />} size="small" />
                                        ) : null}
                                        <span className="font-bold uppercase text-xs my-1 tracking-wide flex-1">
                                            Pinned Recordings
                                        </span>
                                        <span className="rounded p-1 px-2 text-xs bg-border-light">5 of 100</span>
                                    </div>
                                    <ul className="overflow-y-auto">
                                        {pinnedRecordingsResponse?.results.map((rec, i) => (
                                            <Fragment key={rec.id}>
                                                {i > 0 && <div className="border-t" />}
                                                <SessionRecordingPlaylistItem
                                                    recording={rec}
                                                    recordingProperties={sessionRecordingIdToProperties[rec.id]}
                                                    recordingPropertiesLoading={
                                                        sessionRecordingsPropertiesResponseLoading
                                                    }
                                                    onClick={() => onRecordingClick(rec)}
                                                    onPropertyClick={onPropertyClick}
                                                    isActive={activeSessionRecording?.id === rec.id}
                                                />
                                            </Fragment>
                                        ))}
                                    </ul>
                                </div>
                            </>
                        ) : pinnedRecordingsResponseLoading ? (
                            <div className="w-full border border-dashed rounded text-muted-alt p-3">
                                <LemonSkeleton className="my-2" repeat={3} />
                            </div>
                        ) : (
                            <div className="w-full border border-dashed rounded text-muted-alt p-3">
                                <div className="flex items-center gap-2 mb-2">
                                    <h5 className="mb-0">Pinned Recordings</h5>
                                    <Tooltip
                                        title={
                                            <>
                                                You can pin recordings to a playlist to easily keep track of relevant
                                                recordings for the task at hand.
                                                <br />
                                                Pinned recordings are not deleted.
                                            </>
                                        }
                                    >
                                        <IconInfo />
                                    </Tooltip>
                                </div>
                                <span>
                                    Pinned recordings will appear here. You can use this to save particularly
                                    interesting recordings. They will show regardless of any filters set.
                                </span>
                            </div>
                        ))}

                    {/* Other recordings */}

                    <LemonDivider dashed />

                    <div className="w-full overflow-hidden border rounded">
                        <div className="relative flex justify-between items-center p-2 border-b">
                            <span className="flex items-center gap-2">
                                {playlistShortId ? (
                                    <LemonButton status="stealth" icon={<IconUnfoldLess />} size="small" />
                                ) : null}
                                <span className="font-bold uppercase text-xs my-1 tracking-wide">
                                    {!playlistShortId ? 'Recent recordings' : 'Other recordings'}
                                </span>
                            </span>
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
                                    <Fragment key={rec.id}>
                                        {i > 0 && <div className="border-t" />}
                                        <SessionRecordingPlaylistItem
                                            recording={rec}
                                            recordingProperties={sessionRecordingIdToProperties[rec.id]}
                                            recordingPropertiesLoading={sessionRecordingsPropertiesResponseLoading}
                                            onClick={() => onRecordingClick(rec)}
                                            onPropertyClick={onPropertyClick}
                                            isActive={activeSessionRecording?.id === rec.id}
                                        />
                                    </Fragment>
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
                        <SessionRecordingPlayer
                            playerKey="playlist"
                            sessionRecordingId={activeSessionRecording?.id}
                            matching={activeSessionRecording?.matching_events}
                            recordingStartTime={activeSessionRecording ? activeSessionRecording.start_time : undefined}
                            nextSessionRecording={nextSessionRecording}
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
        </>
    )
}
