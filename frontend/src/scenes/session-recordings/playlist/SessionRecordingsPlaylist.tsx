import { useEffect, useRef } from 'react'
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
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft, IconChevronRight, IconFilter, IconWithCount } from 'lib/components/icons'
import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import clsx from 'clsx'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { LemonTableLoader } from 'lib/components/LemonTable/LemonTableLoader'
import { SessionRecordingPlaylistItem } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistItem'
import { SceneExport } from 'scenes/sceneTypes'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { DurationFilter } from '../filters/DurationFilter'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { NotFound } from 'lib/components/NotFound'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'

export const scene: SceneExport = {
    component: SessionRecordingsPlaylistScene,
    logic: sessionRecordingsPlaylistLogic,
    paramsToProps: ({ params: { id } }) => {
        return { shortId: id as string }
    },
}

export function SessionRecordingsPlaylistScene(): JSX.Element {
    const { playlist, playlistLoading, hasChanges } = useValues(sessionRecordingsPlaylistLogic)
    const { updatePlaylist, setFilters, saveChanges } = useActions(sessionRecordingsPlaylistLogic)

    if (!playlist && playlistLoading) {
        return <Spinner />
    }

    if (!playlist) {
        return <NotFound object={'Recording Playlist'} />
    }

    return (
        <div>
            <PageHeader
                title={
                    <EditableField
                        name="name"
                        value={playlist.name || ''}
                        placeholder={'Untitled Playlist'}
                        onSave={(value) => updatePlaylist({ name: value })}
                        saveOnBlur={true}
                        maxLength={400}
                        mode={undefined}
                        data-attr="playlist-name"
                    />
                }
                buttons={
                    <div className="flex justify-between items-center gap-2">
                        <>
                            <LemonButton
                                type="primary"
                                disabled={!hasChanges}
                                loading={hasChanges && playlistLoading}
                                onClick={saveChanges}
                            >
                                Save changes
                            </LemonButton>
                        </>
                    </div>
                }
                caption={
                    <>
                        <EditableField
                            multiline
                            name="description"
                            value={playlist.description || ''}
                            placeholder="Description (optional)"
                            onSave={(value) => updatePlaylist({ description: value })}
                            saveOnBlur={true}
                            maxLength={400}
                            data-attr="playlist-description"
                            compactButtons
                        />
                        <UserActivityIndicator
                            at={playlist.last_modified_at}
                            by={playlist.last_modified_by}
                            className="mt-2"
                        />
                    </>
                }
            />
            {playlist.short_id ? (
                <SessionRecordingsPlaylist
                    logicKey={playlist.short_id}
                    filters={playlist.filters}
                    onFiltersChange={setFilters}
                />
            ) : null}
        </div>
    )
}

export type SessionRecordingsPlaylistProps = {
    logicKey: string
    personUUID?: string
    filters?: RecordingFilters
    updateSearchParams?: boolean
    onFiltersChange?: (filters: RecordingFilters) => void
}

export function SessionRecordingsPlaylist({
    logicKey,
    personUUID,
    filters: defaultFilters,
    updateSearchParams,
    onFiltersChange,
}: SessionRecordingsPlaylistProps): JSX.Element {
    const logic = sessionRecordingsListLogic({ key: logicKey, personUUID, filters: defaultFilters, updateSearchParams })
    const {
        sessionRecordings,
        sessionRecordingIdToProperties,
        sessionRecordingsResponseLoading,
        sessionRecordingsPropertiesResponseLoading,
        hasNext,
        hasPrev,
        activeSessionRecording,
        filters,
        totalFiltersCount,
        showFilters,
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
                    {showFilters ? 'Hide filters' : 'Filter recordings'}
                </LemonButton>

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
                                recordingStartTime={
                                    activeSessionRecording ? activeSessionRecording.start_time : undefined
                                }
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
        </>
    )
}
