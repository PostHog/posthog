import { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { RecordingDurationFilter, RecordingFilters, SessionRecordingType } from '~/types'
import {
    defaultPageviewPropertyEntityFilter,
    RECORDINGS_LIMIT,
    sessionRecordingsListLogic,
} from './sessionRecordingsListLogic'
import './SessionRecordingsPlaylist.scss'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft, IconChevronRight, IconFilter, IconWithCount } from 'lib/components/icons'
import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { DurationFilter } from '../filters/DurationFilter'
import { SessionRecordingsList } from './SessionRecordingsList'
import { StickyView } from 'lib/components/StickyView/StickyView'

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
    const nextLength = offset + (sessionRecordingsResponseLoading ? RECORDINGS_LIMIT : sessionRecordings.length)

    const paginationControls = nextLength ? (
        <div className="flex items-center gap-1 mx-2">
            <span>{`${offset + 1} - ${nextLength}`}</span>
            <LemonButton
                icon={<IconChevronLeft />}
                status="stealth"
                size="small"
                disabled={!hasPrev}
                onClick={() => loadPrev()}
            />
            <LemonButton
                icon={<IconChevronRight />}
                status="stealth"
                disabled={!hasNext}
                size="small"
                onClick={() => loadNext()}
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
                    <StickyView top="3.5rem" marginTop={16}>
                        <div className="SessionRecordingsPlaylist__lists">
                            {showFilters ? (
                                <SessionRecordingsFilters
                                    filters={filters}
                                    setFilters={setFilters}
                                    showPropertyFilters={!personUUID}
                                />
                            ) : null}

                            {/* Pinned recordings */}
                            {!!playlistShortId && !showFilters ? (
                                <>
                                    <SessionRecordingsList
                                        title="Pinned Recordings"
                                        titleRight={
                                            pinnedRecordingsResponse?.results?.length ? (
                                                <span className="rounded py-1 px-2 mr-1 text-xs bg-border-light font-semibold">
                                                    {pinnedRecordingsResponse?.results?.length}
                                                </span>
                                            ) : null
                                        }
                                        onRecordingClick={onRecordingClick}
                                        onPropertyClick={onPropertyClick}
                                        collapsable
                                        recordings={pinnedRecordingsResponse?.results}
                                        loading={pinnedRecordingsResponseLoading}
                                        info={
                                            <>
                                                You can pin recordings to a playlist to easily keep track of relevant
                                                recordings for the task at hand. Pinned recordings are always shown,
                                                regardless of filters and are not deleted.
                                            </>
                                        }
                                        activeRecordingId={activeSessionRecording?.id}
                                    />
                                    {/* <LemonDivider dashed className="my-0" /> */}
                                </>
                            ) : null}

                            {/* Other recordings */}

                            <SessionRecordingsList
                                title={!playlistShortId ? 'Recent recordings' : 'Other recordings'}
                                titleRight={paginationControls}
                                onRecordingClick={onRecordingClick}
                                onPropertyClick={onPropertyClick}
                                collapsable={!!playlistShortId}
                                recordings={sessionRecordings}
                                loading={sessionRecordingsResponseLoading}
                                loadingSkeletonCount={RECORDINGS_LIMIT}
                                empty={<>No matching recordings found</>}
                                activeRecordingId={activeSessionRecording?.id}
                            />
                        </div>
                    </StickyView>
                </div>
                <div className="SessionRecordingsPlaylist__right-column">
                    {activeSessionRecording?.id ? (
                        <SessionRecordingPlayer
                            playerKey="playlist"
                            playlistShortId={playlistShortId}
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
