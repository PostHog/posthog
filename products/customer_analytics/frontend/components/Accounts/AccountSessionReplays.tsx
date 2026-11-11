import { useActions, useValues } from 'kea'
import { useLayoutEffect, useRef } from 'react'

import { LemonBanner, LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import {
    SessionRecordingPreview,
    SessionRecordingPreviewSkeleton,
} from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { teamLogic } from 'scenes/teamLogic'

import { accountSessionReplaysLogic } from './accountSessionReplaysLogic'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'

const MAX_VISIBLE_REPLAY_ROWS = 10

interface AccountSessionReplaysProps extends AccountViewTileLogicProps {
    accountId: string
    externalId: string
}

export function AccountSessionReplays({
    accountId,
    externalId,
    ...tileProps
}: AccountSessionReplaysProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = accountSessionReplaysLogic({ projectId: currentTeamId, accountId, externalId, ...tileProps })
    const { replayList, replayListLoading, dateRange, selectedUser, availableUsers, canViewReplays } = useValues(logic)
    const { setDateRange, setUser, loadMore, retry, openRecording } = useActions(logic)
    const recordings = replayList?.recordings ?? []
    const scrollportRef = useRef<HTMLDivElement>(null)
    const rowsRef = useRef<HTMLDivElement>(null)

    useLayoutEffect(() => {
        const scrollport = scrollportRef.current
        const rows = rowsRef.current
        if (!scrollport || !rows) {
            return
        }
        const visibleRows = Array.from(rows.children).slice(0, MAX_VISIBLE_REPLAY_ROWS)
        const measureHeight = (): void => {
            const firstRow = visibleRows[0]
            const lastRow = visibleRows[visibleRows.length - 1]
            // Preview height varies with content and width. Row bounds also cancel the current scroll offset.
            const height =
                firstRow && lastRow ? lastRow.getBoundingClientRect().bottom - firstRow.getBoundingClientRect().top : 0
            const maxHeight = rows.childElementCount > MAX_VISIBLE_REPLAY_ROWS && height > 0 ? `${height}px` : ''
            if (scrollport.style.maxHeight !== maxHeight) {
                scrollport.style.maxHeight = maxHeight
            }
            scrollport.dataset.heightReady = String(height > 0)
        }
        measureHeight()
        if (typeof ResizeObserver === 'undefined') {
            return
        }
        const observer = new ResizeObserver(measureHeight)
        observer.observe(rows)
        visibleRows.forEach((row) => observer.observe(row, { box: 'border-box' }))
        return () => observer.disconnect()
    }, [recordings, canViewReplays, replayList?.status])

    if (!canViewReplays || replayList?.status === 'denied') {
        return (
            <LemonBanner type="warning" className="mb-2">
                <span data-attr="account-replays-denied">
                    You don't have access to these recordings. Ask a project admin for Customer analytics and Session
                    replay access.
                </span>
            </LemonBanner>
        )
    }

    if (replayList?.status === 'setup') {
        return (
            <LemonBanner type="info" className="mb-2">
                <span data-attr="account-replays-setup">
                    This account isn't linked to analytics. Ask a project admin to configure accounts in Customer
                    analytics settings and link this account.
                </span>
            </LemonBanner>
        )
    }

    const userOptions =
        selectedUser && !availableUsers.some((user) => user.value === selectedUser.value)
            ? [...availableUsers, selectedUser]
            : availableUsers

    return (
        <div className="min-w-0 mb-2 flex flex-col gap-2 ph-no-capture" data-attr="account-session-replays">
            <div className="flex flex-wrap items-center gap-2">
                <DateFilter dateFrom={dateRange.date_from} dateTo={dateRange.date_to} onChange={setDateRange} />
                <LemonSelect<string | null>
                    value={selectedUser?.value ?? null}
                    onChange={(value) => setUser(userOptions.find((user) => user.value === value) ?? null)}
                    options={[{ value: null, label: 'All users' }, ...userOptions]}
                    menu={{ className: 'ph-no-capture' }}
                    size="small"
                    aria-label="Filter recordings by user"
                    data-attr="account-replays-user-filter"
                    tooltip="Users from recordings loaded for this account"
                    truncateText={{ maxWidthClass: 'max-w-48' }}
                />
            </div>
            <p className="mb-0 text-xs text-secondary">
                Recordings include activity for this account. Playback shows the whole session, including activity for
                other accounts.
            </p>
            {replayList?.status === 'error' && (
                <LemonBanner type="error">
                    <div className="flex flex-wrap items-center gap-2" data-attr="account-replays-error">
                        <span>Couldn't load recordings. Try again.</span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={retry}
                            loading={replayListLoading}
                            data-attr="account-replays-retry"
                        >
                            Retry
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}
            {recordings.length > 0 && (
                <div
                    ref={scrollportRef}
                    className="min-h-0 min-w-0 overflow-x-hidden overflow-y-auto"
                    data-attr="account-replays-list"
                >
                    <div ref={rowsRef} className="flex flex-col gap-2">
                        {recordings.map((recording) => (
                            <button
                                key={recording.id}
                                type="button"
                                className="w-full min-w-0 border-0 border-b bg-transparent p-0 text-left cursor-pointer focus-visible:-outline-offset-2 ph-no-capture"
                                onClick={() => openRecording(recording.id)}
                                aria-label="Open recording"
                                data-attr="account-replays-open-recording"
                            >
                                <SessionRecordingPreview recording={recording} order="start_time" />
                            </button>
                        ))}
                    </div>
                </div>
            )}
            {(replayListLoading || !replayList || replayList.status === 'waiting') && recordings.length === 0 && (
                <div aria-label="Loading recordings" data-attr="account-replays-loading">
                    {Array.from({ length: 3 }, (_, index) => (
                        <SessionRecordingPreviewSkeleton key={index} />
                    ))}
                </div>
            )}
            {replayList?.status === 'ready' && !replayListLoading && recordings.length === 0 && (
                <div className="p-4 text-center text-secondary" data-attr="account-replays-empty">
                    No recordings match this account and these filters. Try another date range or clear the user filter.
                </div>
            )}
            {replayList?.status === 'ready' && replayList.hasMore && (
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={loadMore}
                    loading={replayListLoading}
                    fullWidth
                    data-attr="account-replays-load-more"
                >
                    Load more
                </LemonButton>
            )}
        </div>
    )
}
