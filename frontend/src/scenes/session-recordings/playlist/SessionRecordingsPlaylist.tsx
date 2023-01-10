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
import { eventUsageLogic, SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { DurationFilter } from '../filters/DurationFilter'
import { SessionRecordingsList } from './SessionRecordingsList'
import { StickyView } from 'lib/components/StickyView/StickyView'
import { createPlaylist } from './playlistUtils'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'

const MARGIN_TOP = 16

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
    const logicProps = {
        playlistShortId,
        personUUID,
        filters: defaultFilters,
        updateSearchParams,
    }
    const logic = sessionRecordingsListLogic(logicProps)
    const {
        sessionRecordings,
        sessionRecordingsResponseLoading,
        hasNext,
        hasPrev,
        activeSessionRecording,
        nextSessionRecording,
        filters,
        totalFiltersCount,
        showFilters,
        pinnedRecordings,
        pinnedRecordingsResponseLoading,
    } = useValues(logic)
    const { setSelectedRecordingId, loadNext, loadPrev, setFilters, reportRecordingsListFilterAdded, setShowFilters } =
        useActions(logic)
    const { reportRecordingPlaylistCreated } = useActions(eventUsageLogic)
    const playlistRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (filters !== defaultFilters) {
            onFiltersChange?.(filters)
        }
    }, [filters])

    const onRecordingClick = (recording: SessionRecordingType): void => {
        setSelectedRecordingId(recording.id)
    }

    const onPropertyClick = (property: string, value?: string): void => {
        setFilters(defaultPageviewPropertyEntityFilter(filters, property, value))
    }

    const newPlaylistHandler = useAsyncHandler(async () => {
        await createPlaylist({ filters }, true)
        reportRecordingPlaylistCreated('filters')
    })

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

                        {!playlistShortId ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={newPlaylistHandler.onEvent}
                                loading={newPlaylistHandler.loading}
                                data-attr="save-recordings-playlist-button"
                            >
                                Save as playlist
                            </LemonButton>
                        ) : null}
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
                    <StickyView top="3.5rem" marginTop={MARGIN_TOP}>
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
                                <SessionRecordingsList
                                    listKey="pinned"
                                    title="Pinned Recordings"
                                    titleRight={
                                        pinnedRecordings.length ? (
                                            <span className="rounded py-1 px-2 mr-1 text-xs bg-border-light font-semibold">
                                                {pinnedRecordings.length}
                                            </span>
                                        ) : null
                                    }
                                    onRecordingClick={onRecordingClick}
                                    onPropertyClick={onPropertyClick}
                                    collapsable
                                    recordings={pinnedRecordings}
                                    loading={pinnedRecordingsResponseLoading}
                                    info={
                                        <>
                                            You can pin recordings to a playlist to easily keep track of relevant
                                            recordings for the task at hand. Pinned recordings are always shown,
                                            regardless of filters.
                                        </>
                                    }
                                    activeRecordingId={activeSessionRecording?.id}
                                />
                            ) : null}

                            {/* Other recordings */}

                            <SessionRecordingsList
                                listKey="other"
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
