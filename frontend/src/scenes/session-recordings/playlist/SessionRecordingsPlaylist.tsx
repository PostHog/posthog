import './SessionRecordingsPlaylist.scss'

import { IconCollapse, IconFilter, IconGear } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { range } from 'd3'
import { BindLogic, useActions, useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { FEATURE_FLAGS } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconChevronRight, IconWithCount } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React, { useEffect, useRef } from 'react'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { urls } from 'scenes/urls'

import { ReplayTabs, SessionRecordingType } from '~/types'

import { SessionRecordingsFilters } from '../filters/SessionRecordingsFilters'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { SessionRecordingPreview, SessionRecordingPreviewSkeleton } from './SessionRecordingPreview'
import {
    DEFAULT_RECORDING_FILTERS,
    RECORDINGS_LIMIT,
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistSettings } from './SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'

const SCROLL_TRIGGER_OFFSET = 100

const CounterBadge = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <span className="rounded py-1 px-2 mr-1 text-xs bg-border-light font-semibold select-none">{children}</span>
)

function UnusableEventsWarning(props: { unusableEventsInFilter: string[] }): JSX.Element {
    // TODO add docs on how to enrich custom events with session_id and link to it from here
    return (
        <LemonBanner type="warning">
            <p>Cannot use these events to filter for session recordings:</p>
            <li className="my-1">
                {props.unusableEventsInFilter.map((event) => (
                    <span key={event}>"{event}"</span>
                ))}
            </li>
            <p>
                Events have to have a <PropertyKeyInfo value="$session_id" /> to be used to filter recordings. This is
                added automatically by{' '}
                <Link to="https://posthog.com/docs/libraries/js" target="_blank">
                    the Web SDK
                </Link>
                ,{' '}
                <Link to="https://posthog.com/docs/libraries/android" target="_blank">
                    the Android SDK
                </Link>
            </p>
        </LemonBanner>
    )
}

function PinnedRecordingsList(): JSX.Element | null {
    const { setSelectedRecordingId } = useActions(sessionRecordingsPlaylistLogic)
    const { activeSessionRecordingId, pinnedRecordings } = useValues(sessionRecordingsPlaylistLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'

    const description = isTestingSaved ? 'Saved' : 'Pinned'

    if (!pinnedRecordings.length) {
        return null
    }

    return (
        <>
            <div className="flex justify-between items-center pl-3 pr-1 py-2 text-muted-alt border-b uppercase font-semibold text-xs">
                {description} recordings
            </div>
            {pinnedRecordings.map((rec) => (
                <div key={rec.id} className="border-b">
                    <SessionRecordingPreview
                        recording={rec}
                        onClick={() => setSelectedRecordingId(rec.id)}
                        isActive={activeSessionRecordingId === rec.id}
                        pinned={true}
                    />
                </div>
            ))}
        </>
    )
}

function RecordingsLists(): JSX.Element {
    const {
        filters,
        advancedFilters,
        simpleFilters,
        hasNext,
        pinnedRecordings,
        otherRecordings,
        sessionRecordingsResponseLoading,
        activeSessionRecordingId,
        showFilters,
        showSettings,
        totalFiltersCount,
        sessionRecordingsAPIErrored,
        unusableEventsInFilter,
        logicProps,
        showOtherRecordings,
        recordingsCount,
        isRecordingsListCollapsed,
        sessionSummaryLoading,
    } = useValues(sessionRecordingsPlaylistLogic)
    const {
        setSelectedRecordingId,
        setAdvancedFilters,
        setSimpleFilters,
        maybeLoadSessionRecordings,
        setShowFilters,
        setShowSettings,
        resetFilters,
        toggleShowOtherRecordings,
        toggleRecordingsListCollapsed,
        summarizeSession,
    } = useActions(sessionRecordingsPlaylistLogic)

    const onRecordingClick = (recording: SessionRecordingType): void => {
        setSelectedRecordingId(recording.id)
    }

    const onSummarizeClick = (recording: SessionRecordingType): void => {
        summarizeSession(recording.id)
    }

    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        // If we are scrolling down then check if we are at the bottom of the list
        if (e.currentTarget.scrollTop > lastScrollPositionRef.current) {
            const scrollPosition = e.currentTarget.scrollTop + e.currentTarget.clientHeight
            if (e.currentTarget.scrollHeight - scrollPosition < SCROLL_TRIGGER_OFFSET) {
                maybeLoadSessionRecordings('older')
            }
        }

        // Same again but if scrolling to the top
        if (e.currentTarget.scrollTop < lastScrollPositionRef.current) {
            if (e.currentTarget.scrollTop < SCROLL_TRIGGER_OFFSET) {
                maybeLoadSessionRecordings('newer')
            }
        }

        lastScrollPositionRef.current = e.currentTarget.scrollTop
    }

    useEffect(() => {
        if (contentRef.current) {
            contentRef.current.scrollTop = 0
        }
    }, [showFilters, showSettings])

    const notebookNode = useNotebookNode()

    return isRecordingsListCollapsed ? (
        <div className="flex items-start h-full bg-bg-light border-r p-1">
            <LemonButton size="small" icon={<IconChevronRight />} onClick={() => toggleRecordingsListCollapsed()} />
        </div>
    ) : (
        <div className="flex flex-col w-full bg-bg-light overflow-hidden border-r h-full">
            <DraggableToNotebook href={urls.replay(ReplayTabs.Recent, filters)}>
                <div className="shrink-0 relative flex justify-between items-center p-1 gap-1 whitespace-nowrap border-b">
                    <LemonButton
                        size="small"
                        icon={<IconCollapse className="rotate-90" />}
                        onClick={() => toggleRecordingsListCollapsed()}
                    />
                    <span className="py-1 flex flex-1 gap-2">
                        {!notebookNode ? (
                            <span className="font-bold uppercase text-xs my-1 tracking-wide flex gap-1 items-center">
                                Recordings
                            </span>
                        ) : null}
                        <Tooltip
                            placement="bottom"
                            title={
                                <>
                                    Showing {recordingsCount} results.
                                    <br />
                                    Scrolling to the bottom or the top of the list will load older or newer recordings
                                    respectively.
                                </>
                            }
                        >
                            <span>
                                <CounterBadge>{Math.min(999, recordingsCount)}+</CounterBadge>
                            </span>
                        </Tooltip>
                    </span>
                    <LemonButton
                        tooltip="Filter recordings"
                        size="small"
                        active={showFilters}
                        icon={
                            <IconWithCount count={totalFiltersCount}>
                                <IconFilter />
                            </IconWithCount>
                        }
                        onClick={() => {
                            if (notebookNode) {
                                notebookNode.actions.toggleEditing()
                            } else {
                                setShowFilters(!showFilters)
                            }
                        }}
                    >
                        Filter
                    </LemonButton>
                    <LemonButton
                        tooltip="Playlist settings"
                        size="small"
                        active={showSettings}
                        icon={<IconGear />}
                        onClick={() => setShowSettings(!showSettings)}
                    />
                    <LemonTableLoader loading={sessionRecordingsResponseLoading} />
                </div>
            </DraggableToNotebook>

            <div className={clsx('overflow-y-auto')} onScroll={handleScroll} ref={contentRef}>
                {!notebookNode && showFilters ? (
                    <div className="bg-side border-b">
                        <SessionRecordingsFilters
                            advancedFilters={advancedFilters}
                            simpleFilters={simpleFilters}
                            setAdvancedFilters={setAdvancedFilters}
                            setSimpleFilters={setSimpleFilters}
                            hideSimpleFilters={logicProps.hideSimpleFilters}
                            showPropertyFilters={!logicProps.personUUID}
                            onReset={resetFilters}
                        />
                    </div>
                ) : showSettings ? (
                    <SessionRecordingsPlaylistSettings />
                ) : null}

                {pinnedRecordings.length || otherRecordings.length ? (
                    <ul>
                        <PinnedRecordingsList />

                        {pinnedRecordings.length ? (
                            <div className="flex justify-between items-center pl-3 pr-1 py-2 text-muted-alt border-b uppercase font-semibold text-xs">
                                Other recordings
                                <LemonButton size="xsmall" onClick={() => toggleShowOtherRecordings()}>
                                    {showOtherRecordings ? 'Hide' : 'Show'}
                                </LemonButton>
                            </div>
                        ) : null}

                        <>
                            {showOtherRecordings
                                ? otherRecordings.map((rec) => (
                                      <div key={rec.id} className="border-b">
                                          <SessionRecordingPreview
                                              recording={rec}
                                              onClick={() => onRecordingClick(rec)}
                                              isActive={activeSessionRecordingId === rec.id}
                                              pinned={false}
                                              summariseFn={onSummarizeClick}
                                              sessionSummaryLoading={sessionSummaryLoading}
                                          />
                                      </div>
                                  ))
                                : null}

                            <div className="m-4 h-10 flex items-center justify-center gap-2 text-muted-alt">
                                {!showOtherRecordings && totalFiltersCount ? (
                                    <>Filters do not apply to pinned recordings</>
                                ) : sessionRecordingsResponseLoading ? (
                                    <>
                                        <Spinner textColored /> Loading older recordings
                                    </>
                                ) : hasNext ? (
                                    <LemonButton onClick={() => maybeLoadSessionRecordings('older')}>
                                        Load more
                                    </LemonButton>
                                ) : (
                                    'No more results'
                                )}
                            </div>
                        </>
                    </ul>
                ) : sessionRecordingsResponseLoading ? (
                    <>
                        {range(RECORDINGS_LIMIT).map((i) => (
                            <SessionRecordingPreviewSkeleton key={i} />
                        ))}
                    </>
                ) : (
                    <div className="p-3 text-sm text-muted-alt">
                        {sessionRecordingsAPIErrored ? (
                            <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
                        ) : unusableEventsInFilter.length ? (
                            <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
                        ) : (
                            <div className="flex flex-col items-center space-y-2">
                                {filters.date_from === DEFAULT_RECORDING_FILTERS.date_from ? (
                                    <>
                                        <span>No matching recordings found</span>
                                        <LemonButton
                                            type="secondary"
                                            data-attr="expand-replay-listing-from-default-seven-days-to-twenty-one"
                                            onClick={() => {
                                                setAdvancedFilters({
                                                    date_from: '-30d',
                                                })
                                            }}
                                        >
                                            Search over the last 30 days
                                        </LemonButton>
                                    </>
                                ) : (
                                    <SessionRecordingsPlaylistTroubleshooting />
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}

export function SessionRecordingsPlaylist(props: SessionRecordingPlaylistLogicProps): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
    }
    const playlistRecordingsListRef = useRef<HTMLDivElement>(null)
    const logic = sessionRecordingsPlaylistLogic(logicProps)
    const {
        activeSessionRecording,
        activeSessionRecordingId,
        matchingEventsMatchType,
        pinnedRecordings,
        isRecordingsListCollapsed,
    } = useValues(logic)
    const { toggleRecordingsListCollapsed } = useActions(logic)

    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    const notebookNode = useNotebookNode()

    return (
        <>
            <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
                <div
                    ref={playlistRef}
                    data-attr="session-recordings-playlist"
                    className={clsx('SessionRecordingsPlaylist', {
                        'SessionRecordingsPlaylist--wide': size !== 'small',
                        'SessionRecordingsPlaylist--embedded': notebookNode,
                    })}
                >
                    <div
                        ref={playlistRecordingsListRef}
                        className={clsx(
                            'SessionRecordingsPlaylist__list',
                            isRecordingsListCollapsed && 'SessionRecordingsPlaylist__list--collapsed'
                        )}
                    >
                        <RecordingsLists />
                        <Resizer
                            logicKey="player-recordings-list"
                            placement="right"
                            containerRef={playlistRecordingsListRef}
                            closeThreshold={100}
                            onToggleClosed={(shouldBeClosed) => toggleRecordingsListCollapsed(shouldBeClosed)}
                            onDoubleClick={() => toggleRecordingsListCollapsed()}
                        />
                    </div>
                    <div className="SessionRecordingsPlaylist__player">
                        {activeSessionRecordingId ? (
                            <SessionRecordingPlayer
                                playerKey={props.logicKey ?? 'playlist'}
                                sessionRecordingId={activeSessionRecordingId}
                                matchingEventsMatchType={matchingEventsMatchType}
                                playlistLogic={logic}
                                noBorder
                                pinned={!!pinnedRecordings.find((x) => x.id === activeSessionRecordingId)}
                                setPinned={
                                    props.onPinnedChange
                                        ? (pinned) => {
                                              if (!activeSessionRecording?.id) {
                                                  return
                                              }
                                              props.onPinnedChange?.(activeSessionRecording, pinned)
                                          }
                                        : undefined
                                }
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
            </BindLogic>
        </>
    )
}
