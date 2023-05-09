import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { RecordingFilters, SessionRecordingType } from '~/types'
import {
    defaultPageviewPropertyEntityFilter,
    RECORDINGS_LIMIT,
    sessionRecordingsListLogic,
} from './sessionRecordingsListLogic'
import './SessionRecordingsPlaylist.scss'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import { SessionRecordingsList } from './SessionRecordingsList'
import clsx from 'clsx'
import { SessionRecordingsPlaylistFilters } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylistFilters'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

const CounterBadge = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <span className="rounded py-1 px-2 mr-1 text-xs bg-border-light font-semibold select-none">{children}</span>
)

export function RecordingsLists({
    playlistShortId,
    personUUID,
    filters: defaultFilters,
    updateSearchParams,
}: SessionRecordingsPlaylistProps): JSX.Element {
    const logicProps = {
        playlistShortId,
        personUUID,
        filters: defaultFilters,
        updateSearchParams,
    }
    const logic = sessionRecordingsListLogic(logicProps)
    const {
        filters,
        hasNext,
        hasPrev,
        sessionRecordings,
        sessionRecordingsResponseLoading,
        activeSessionRecording,
        showFilters,
        pinnedRecordingsResponse,
        pinnedRecordingsResponseLoading,
    } = useValues(logic)
    const { setSelectedRecordingId, loadNext, loadPrev, setFilters, maybeLoadSessionRecordings } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const infiniteScrollerEnabled = featureFlags[FEATURE_FLAGS.SESSION_RECORDING_INFINITE_LIST]

    const [collapsed, setCollapsed] = useState({ pinned: false, other: false })
    const offset = filters.offset ?? 0
    const nextLength = offset + (sessionRecordingsResponseLoading ? RECORDINGS_LIMIT : sessionRecordings.length)

    const onRecordingClick = (recording: SessionRecordingType): void => {
        setSelectedRecordingId(recording.id)
    }

    const onPropertyClick = (property: string, value?: string): void => {
        setFilters(defaultPageviewPropertyEntityFilter(filters, property, value))
    }

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
            {/* Pinned recordings */}
            {!!playlistShortId && !showFilters ? (
                <SessionRecordingsList
                    className={clsx({
                        'max-h-1/2 h-fit': !collapsed.other,
                        'shrink-1': !collapsed.pinned && collapsed.other,
                    })}
                    listKey="pinned"
                    title="Pinned Recordings"
                    titleRight={
                        pinnedRecordingsResponse?.results?.length ? (
                            <CounterBadge>{pinnedRecordingsResponse.results.length}</CounterBadge>
                        ) : null
                    }
                    onRecordingClick={onRecordingClick}
                    onPropertyClick={onPropertyClick}
                    collapsed={collapsed.pinned}
                    onCollapse={() => setCollapsed({ ...collapsed, pinned: !collapsed.pinned })}
                    recordings={pinnedRecordingsResponse?.results}
                    loading={pinnedRecordingsResponseLoading}
                    info={
                        <>
                            You can pin recordings to a playlist to easily keep track of relevant recordings for the
                            task at hand. Pinned recordings are always shown, regardless of filters.
                        </>
                    }
                    activeRecordingId={activeSessionRecording?.id}
                />
            ) : null}

            {/* Other recordings */}
            <SessionRecordingsList
                className={clsx({
                    'flex-1': !collapsed.other,
                    'shrink-0': collapsed.other,
                })}
                listKey="other"
                title={!playlistShortId ? 'Recordings' : 'Other recordings'}
                titleRight={
                    infiniteScrollerEnabled ? (
                        sessionRecordings.length ? (
                            <Tooltip
                                placement="bottom"
                                title={
                                    <>
                                        Showing {sessionRecordings.length} results.
                                        <br />
                                        Scrolling to the bottom or the top of the list will load older or newer
                                        recordings respectively.
                                    </>
                                }
                            >
                                <CounterBadge>{Math.min(999, sessionRecordings.length)}+</CounterBadge>
                            </Tooltip>
                        ) : null
                    ) : (
                        paginationControls
                    )
                }
                onRecordingClick={onRecordingClick}
                onPropertyClick={onPropertyClick}
                collapsed={collapsed.other}
                onCollapse={
                    !!playlistShortId ? () => setCollapsed({ ...collapsed, other: !collapsed.other }) : undefined
                }
                recordings={sessionRecordings}
                loading={sessionRecordingsResponseLoading}
                loadingSkeletonCount={RECORDINGS_LIMIT}
                empty={<>No matching recordings found</>}
                activeRecordingId={activeSessionRecording?.id}
                onScrollToEnd={infiniteScrollerEnabled ? () => maybeLoadSessionRecordings('older') : undefined}
                onScrollToStart={infiniteScrollerEnabled ? () => maybeLoadSessionRecordings('newer') : undefined}
                footer={
                    infiniteScrollerEnabled ? (
                        <>
                            <LemonDivider />
                            <div className="m-4 h-10 flex items-center justify-center gap-2 text-muted-alt">
                                {sessionRecordingsResponseLoading ? (
                                    <>
                                        <Spinner monocolor /> Loading older recordings
                                    </>
                                ) : hasNext ? (
                                    <LemonButton status="primary" onClick={() => maybeLoadSessionRecordings('older')}>
                                        Load more
                                    </LemonButton>
                                ) : (
                                    'No more results'
                                )}
                            </div>
                        </>
                    ) : null
                }
            />
        </>
    )
}

export type SessionRecordingsPlaylistProps = {
    playlistShortId?: string
    personUUID?: string
    filters?: RecordingFilters
    updateSearchParams?: boolean
    onFiltersChange?: (filters: RecordingFilters) => void
}

export function SessionRecordingsPlaylist(props: SessionRecordingsPlaylistProps): JSX.Element {
    const { playlistShortId, personUUID, filters: defaultFilters, updateSearchParams, onFiltersChange } = props
    const logicProps = {
        playlistShortId,
        personUUID,
        filters: defaultFilters,
        updateSearchParams,
    }
    const logic = sessionRecordingsListLogic(logicProps)
    const { activeSessionRecording, nextSessionRecording, filters, showFilters } = useValues(logic)
    const { setFilters } = useActions(logic)

    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    useEffect(() => {
        if (filters !== defaultFilters) {
            onFiltersChange?.(filters)
        }
    }, [filters])

    const lists = (
        <div className="SessionRecordingsPlaylist__lists">
            {showFilters ? (
                <SessionRecordingsFilters filters={filters} setFilters={setFilters} showPropertyFilters={!personUUID} />
            ) : null}
            <RecordingsLists {...props} />
        </div>
    )

    return (
        <>
            <SessionRecordingsPlaylistFilters {...props} />
            <div
                ref={playlistRef}
                data-attr="session-recordings-playlist"
                className={clsx('SessionRecordingsPlaylist', {
                    'SessionRecordingsPlaylist--wide': size !== 'small',
                })}
            >
                <div className={clsx('SessionRecordingsPlaylist__left-column space-y-4')}>{lists}</div>
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
