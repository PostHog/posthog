import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { RecordingFilters, SessionRecordingType, ReplayTabs, ProductKey } from '~/types'
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
import { LemonButton, LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'
import { IconMagnifier, IconPause, IconPlay, IconSettings, IconWithCount } from 'lib/lemon-ui/icons'
import { SessionRecordingsList } from './SessionRecordingsList'
import clsx from 'clsx'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { urls } from 'scenes/urls'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { openSessionRecordingSettingsDialog } from '../settings/SessionRecordingSettings'
import { teamLogic } from 'scenes/teamLogic'
import { router } from 'kea-router'
import { userLogic } from 'scenes/userLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

const CounterBadge = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <span className="rounded py-1 px-2 mr-1 text-xs bg-border-light font-semibold select-none">{children}</span>
)

function UnusableEventsWarning(props: { unusableEventsInFilter: string[] }): JSX.Element {
    // TODO add docs on how to enrich custom events with session_id and link to it from here
    return (
        <LemonBanner type="warning">
            <p>Cannot use these events to filter for session recordings:</p>
            <li className={'my-1'}>
                {props.unusableEventsInFilter.map((event) => (
                    <span key={event}>"{event}"</span>
                ))}
            </li>
            <p>
                Events have to have a <PropertyKeyInfo value={'$session_id'} /> to be used to filter recordings. This is
                added automatically by{' '}
                <Link to={'https://posthog.com/docs/libraries/js'} target={'_blank'}>
                    the Web SDK
                </Link>
            </p>
        </LemonBanner>
    )
}

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
        pinnedRecordingsResponse,
        pinnedRecordingsResponseLoading,
        totalFiltersCount,
        listingVersion,
        sessionRecordingsAPIErrored,
        pinnedRecordingsAPIErrored,
        unusableEventsInFilter,
    } = useValues(logic)
    const { setSelectedRecordingId, setFilters, maybeLoadSessionRecordings, resetFilters } = useActions(logic)
    const { autoplayDirection, showFilters } = useValues(playerSettingsLogic)
    const { toggleAutoplayDirection, setShowFilters } = useActions(playerSettingsLogic)
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
                        empty={
                            pinnedRecordingsAPIErrored ? (
                                <LemonBanner type="error">Error while trying to load pinned recordings.</LemonBanner>
                            ) : !!unusableEventsInFilter.length ? (
                                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
                            ) : undefined
                        }
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
                                        aria-label="Autoplay next recording"
                                        checked={!!autoplayDirection}
                                        onChange={toggleAutoplayDirection}
                                        handleContent={
                                            <span
                                                className={clsx(
                                                    'transition-all flex items-center',
                                                    !autoplayDirection && 'text-border text-sm',
                                                    !!autoplayDirection && 'text-white text-xs pl-px',
                                                    autoplayDirection === 'newer' && 'rotate-180'
                                                )}
                                            >
                                                {autoplayDirection ? <IconPlay /> : <IconPause />}
                                            </span>
                                        }
                                    />
                                </span>
                            </Tooltip>

                            <LemonButton
                                tooltip={'filter recordings'}
                                size="small"
                                status={showFilters ? 'primary' : 'primary-alt'}
                                type={showFilters ? 'tertiary' : 'tertiary'}
                                active={showFilters}
                                icon={
                                    <IconWithCount count={totalFiltersCount}>
                                        <IconMagnifier />
                                    </IconWithCount>
                                }
                                onClick={() => setShowFilters(!showFilters)}
                            />
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
                        sessionRecordingsAPIErrored ? (
                            <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
                        ) : !!unusableEventsInFilter.length ? (
                            <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
                        ) : (
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
                        )
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
                                        <Spinner textColored /> Loading older recordings
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
    const { activeSessionRecording, nextSessionRecording, shouldShowEmptyState, sessionRecordingsResponseLoading } =
        useValues(logic)
    const { currentTeam } = useValues(teamLogic)
    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const shouldShowProductIntroduction =
        !sessionRecordingsResponseLoading &&
        !user?.has_seen_product_intro_for?.[ProductKey.SESSION_REPLAY] &&
        !!featureFlags[FEATURE_FLAGS.SHOW_PRODUCT_INTRO_EXISTING_PRODUCTS]

    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    return (
        <>
            {/* This was added around Jun 23 so at some point can just be removed */}
            <LemonBanner dismissKey="replay-filter-change" type="info" className="mb-4 leading-7">
                <b>Filters have moved!</b> You can now find all filters including time and duration by clicking the{' '}
                <span className="mx-1 text-lg">
                    <IconMagnifier />
                </span>
                icon at the top of the list of recordings.
            </LemonBanner>
            {(shouldShowProductIntroduction || shouldShowEmptyState) && (
                <ProductIntroduction
                    productName="Session replay"
                    productKey={ProductKey.SESSION_REPLAY}
                    thingName="recording"
                    titleOverride="Record your first session"
                    description={`Session replay allows you to watch how real users use your product.
                    ${
                        recordingsDisabled
                            ? 'Enable recordings to get started.'
                            : 'Install the PostHog snippet on your website to start capturing recordings.'
                    }`}
                    isEmpty={shouldShowEmptyState}
                    docsURL="https://posthog.com/docs/session-replay/manual"
                    actionElementOverride={
                        recordingsDisabled ? (
                            <LemonButton
                                type="primary"
                                sideIcon={<IconSettings />}
                                onClick={() => openSessionRecordingSettingsDialog()}
                            >
                                Enable recordings
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                onClick={() => router.actions.push(urls.projectSettings() + '#snippet')}
                            >
                                Get the PostHog snippet
                            </LemonButton>
                        )
                    }
                />
            )}
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
