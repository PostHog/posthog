import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { RecordingFilters, SessionRecordingType, ReplayTabs } from '~/types'
import {
    DEFAULT_RECORDING_FILTERS,
    defaultPageviewPropertyEntityFilter,
    RECORDINGS_LIMIT,
    SessionRecordingListLogicProps,
    sessionRecordingsListLogic,
} from './sessionRecordingsListLogic'
import './SessionRecordingsPlaylist.scss'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { IconFilter, IconPause, IconPlay, IconWithCount } from 'lib/lemon-ui/icons'
import { SessionRecordingsList } from './SessionRecordingsList'
import clsx from 'clsx'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { urls } from 'scenes/urls'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

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
        sessionRecordings,
        sessionRecordingsResponseLoading,
        activeSessionRecording,
        showFilters,
        pinnedRecordingsResponse,
        pinnedRecordingsResponseLoading,
        totalFiltersCount,
        listingVersion,
    } = useValues(logic)
    const { setSelectedRecordingId, setFilters, maybeLoadSessionRecordings, setShowFilters, resetFilters } =
        useActions(logic)
    const { autoplayDirection } = useValues(playerSettingsLogic)
    const { toggleAutoplayDirection } = useActions(playerSettingsLogic)
    const [collapsed, setCollapsed] = useState({ pinned: false, other: false })

    const onRecordingClick = (recording: SessionRecordingType): void => {
        setSelectedRecordingId(recording.id)
    }

    const onPropertyClick = (property: string, value?: string): void => {
        setFilters(defaultPageviewPropertyEntityFilter(filters, property, value))
    }

    return (
        <>
            <div className="SessionRecordingsPlaylist__lists">
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
                        <>
                            {sessionRecordings.length ? (
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
                                    <span>
                                        <CounterBadge>{Math.min(999, sessionRecordings.length)}+</CounterBadge>
                                    </span>
                                </Tooltip>
                            ) : null}

                            <LemonButton
                                noPadding
                                status={showFilters ? 'primary' : 'primary-alt'}
                                type={showFilters ? 'primary' : 'tertiary'}
                                icon={
                                    <IconWithCount count={totalFiltersCount}>
                                        <IconFilter />
                                    </IconWithCount>
                                }
                                onClick={() => setShowFilters(!showFilters)}
                            />

                            <Tooltip
                                title={
                                    <div className="text-center">
                                        Autoplay next recording
                                        <br />({!autoplayDirection ? 'disabled' : autoplayDirection})
                                    </div>
                                }
                                placement="bottom"
                            >
                                <span>
                                    <LemonSwitch
                                        checked={!!autoplayDirection}
                                        onChange={toggleAutoplayDirection}
                                        handleContent={
                                            <span
                                                className={clsx(
                                                    'transition-all flex items-center',
                                                    !autoplayDirection && 'text-border text-sm',
                                                    !!autoplayDirection && 'text-primary-highlight text-xs pl-px',
                                                    autoplayDirection === 'newer' && 'rotate-180'
                                                )}
                                            >
                                                {autoplayDirection ? <IconPlay /> : <IconPause />}
                                            </span>
                                        }
                                    />
                                </span>
                            </Tooltip>
                        </>
                    }
                    subheader={
                        showFilters ? (
                            <SessionRecordingsFilters
                                filters={filters}
                                setFilters={setFilters}
                                showPropertyFilters={!personUUID}
                                onReset={totalFiltersCount ? () => resetFilters() : undefined}
                                usesListingV3={listingVersion === '3'}
                            />
                        ) : null
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
                    empty={
                        <div className={'flex flex-col items-center space-y-2'}>
                            <span>No matching recordings found</span>
                            {filters.date_from === DEFAULT_RECORDING_FILTERS.date_from && (
                                <>
                                    <LemonButton
                                        type={'secondary'}
                                        data-attr={'expand-replay-listing-from-default-seven-days-to-twenty-one'}
                                        onClick={() => {
                                            setFilters({
                                                date_from: '-21d',
                                            })
                                        }}
                                    >
                                        Search over the last 21 days
                                    </LemonButton>
                                </>
                            )}
                        </div>
                    }
                    activeRecordingId={activeSessionRecording?.id}
                    onScrollToEnd={() => maybeLoadSessionRecordings('older')}
                    onScrollToStart={() => maybeLoadSessionRecordings('newer')}
                    footer={
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
                    }
                    draggableHref={urls.replay(ReplayTabs.Recent, filters)}
                />
            </div>
        </>
    )
}

export type SessionRecordingsPlaylistProps = {
    playlistShortId?: string
    personUUID?: string
    filters?: RecordingFilters
    updateSearchParams?: boolean
    onFiltersChange?: (filters: RecordingFilters) => void
    autoPlay?: boolean
    mode?: 'standard' | 'notebook'
}

export function SessionRecordingsPlaylist(props: SessionRecordingsPlaylistProps): JSX.Element {
    const {
        playlistShortId,
        personUUID,
        filters: defaultFilters,
        updateSearchParams,
        onFiltersChange,
        autoPlay = true,
    } = props

    const logicProps: SessionRecordingListLogicProps = {
        playlistShortId,
        personUUID,
        filters: defaultFilters,
        updateSearchParams,
        autoPlay,
        onFiltersChange,
    }
    const logic = sessionRecordingsListLogic(logicProps)
    const { activeSessionRecording, nextSessionRecording } = useValues(logic)

    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    return (
        <>
            {/* This was added around Jun 23 so at some point can just be removed */}
            <LemonBanner dismissKey="replay-filter-change" type="info" className="mb-2">
                <b>Filters have moved!</b> You can now find all filters including time and duration by clicking the{' '}
                <span className="mx-1 text-lg">
                    <IconFilter />
                </span>
                icon at the top of the list of recordings.
            </LemonBanner>
            <div
                ref={playlistRef}
                data-attr="session-recordings-playlist"
                className={clsx('SessionRecordingsPlaylist', {
                    'SessionRecordingsPlaylist--wide': size !== 'small',
                })}
            >
                <div className={clsx('SessionRecordingsPlaylist__left-column space-y-4')}>
                    <RecordingsLists {...props} />
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
