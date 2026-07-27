import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { cn } from 'lib/utils/css-classes'

import { SessionDetailPanel } from './AIObservabilitySessionScene'
import { SessionListRow, aiObservabilitySessionsViewLogic } from './tabs/aiObservabilitySessionsViewLogic'
import { formatLLMCost } from './utils'

const SESSION_LIST_DEFAULT_WIDTH = 300
const SESSION_LIST_MIN_WIDTH = 260
const SESSION_LIST_MAX_WIDTH = '50%'

export function AIObservabilitySessionsPlaylist(): JSX.Element {
    const { loadSessions } = useActions(aiObservabilitySessionsViewLogic)
    const { isWindowLessThan } = useWindowSize()
    const isVertical = isWindowLessThan('xl')

    useEffect(() => {
        loadSessions()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
        <div
            className={cn(
                'w-full h-[calc(100vh-13rem)] min-h-[25rem] flex gap-2',
                isVertical ? 'flex-col' : 'flex-row'
            )}
        >
            {isVertical ? (
                <>
                    <DetailPane className="flex-1 min-h-0 overflow-y-auto" />
                    <ListPane className="h-72 shrink-0" />
                </>
            ) : (
                <HorizontalLayout />
            )}
        </div>
    )
}

function HorizontalLayout(): JSX.Element {
    const listRef = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'llma-sessions-list',
        containerRef: listRef,
        persistent: true,
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))
    const listWidth = Math.max(desiredSize ?? SESSION_LIST_DEFAULT_WIDTH, SESSION_LIST_MIN_WIDTH)

    return (
        <>
            <div
                ref={listRef}
                className="relative flex flex-col shrink-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: listWidth, minWidth: SESSION_LIST_MIN_WIDTH, maxWidth: SESSION_LIST_MAX_WIDTH }}
            >
                <ListPane className="h-full" />
                <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
            </div>
            <DetailPane className="flex-1 min-w-0 h-full overflow-y-auto" />
        </>
    )
}

function DetailPane({ className }: { className?: string }): JSX.Element {
    const { selectedSessionId } = useValues(aiObservabilitySessionsViewLogic)
    return (
        <div className={cn('rounded border border-primary bg-surface-primary p-4', className)}>
            {selectedSessionId ? (
                <SessionDetailPanel />
            ) : (
                <div className="h-full flex items-center justify-center text-sm text-secondary">
                    Select a session to view it
                </div>
            )}
        </div>
    )
}

function ListPane({ className }: { className?: string }): JSX.Element {
    const { sessions, sessionsLoading, selectedSessionId, getSessionTitle, hasMoreSessions, moreSessionsLoading } =
        useValues(aiObservabilitySessionsViewLogic)
    const { selectSession, loadMoreSessions } = useActions(aiObservabilitySessionsViewLogic)

    return (
        <div
            className={cn(
                'relative flex flex-col min-h-0 overflow-hidden rounded border border-primary bg-surface-primary',
                className
            )}
        >
            <LemonTableLoader loading={sessionsLoading && sessions.length > 0} placement="top" />
            <div className="flex-1 min-h-0 overflow-y-auto" data-attr="llma-sessions-list">
                {sessionsLoading && sessions.length === 0 ? (
                    <div className="flex flex-col gap-2 p-2">
                        {Array.from({ length: 6 }).map((_, i) => (
                            <LemonSkeleton key={i} className="h-12 w-full" />
                        ))}
                    </div>
                ) : sessions.length === 0 ? (
                    <div className="p-4 text-center text-sm text-secondary">No sessions yet</div>
                ) : (
                    <>
                        <ul className="flex flex-col list-none pl-0 m-0 divide-y divide-primary">
                            {sessions.map((session) => (
                                <li key={session.sessionId}>
                                    <SessionPreview
                                        session={session}
                                        title={getSessionTitle(session.sessionId)}
                                        isActive={session.sessionId === selectedSessionId}
                                        onClick={() => selectSession(session.sessionId)}
                                    />
                                </li>
                            ))}
                        </ul>
                        {hasMoreSessions && (
                            <div className="border-t border-primary p-2">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    fullWidth
                                    loading={moreSessionsLoading}
                                    onClick={loadMoreSessions}
                                    data-attr="llma-load-more-sessions"
                                >
                                    Load more sessions
                                </LemonButton>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}

function SessionPreview({
    session,
    title,
    isActive,
    onClick,
}: {
    session: SessionListRow
    // `undefined` while the title loads, `null` when no usable title was found.
    title: string | null | undefined
    isActive: boolean
    onClick: () => void
}): JSX.Element {
    const fallbackLabel = session.distinctId || 'unknown'

    return (
        <button
            type="button"
            aria-pressed={isActive}
            onClick={onClick}
            className={cn(
                'ph-no-capture w-full min-w-0 text-left cursor-pointer border-l-2 px-2 py-1.5 text-xs flex flex-col gap-1',
                isActive
                    ? 'border-l-accent bg-accent-highlight-secondary'
                    : 'border-l-transparent hover:bg-accent-highlight-secondary'
            )}
            data-attr="llma-session-preview"
        >
            <div className="flex min-w-0 items-center justify-between gap-2">
                {title === undefined ? (
                    <LemonSkeleton className="h-4 w-40" />
                ) : (
                    <span
                        className={cn('min-w-0 truncate', title ? 'font-semibold' : 'font-mono')}
                        title={title || undefined}
                    >
                        {title || fallbackLabel}
                    </span>
                )}
                <span className="shrink-0 text-secondary">
                    <TZLabel time={session.lastSeen} />
                </span>
            </div>
            <div className="flex min-w-0 items-center justify-between gap-2 text-secondary">
                <span className="min-w-0 font-mono truncate">{fallbackLabel}</span>
                <span className="flex shrink-0 items-center gap-2">
                    <span>
                        {session.traces} {session.traces === 1 ? 'trace' : 'traces'}
                    </span>
                    {session.errors > 0 && <span className="text-danger">{session.errors} err</span>}
                    {session.totalCost > 0 && <span>{formatLLMCost(session.totalCost)}</span>}
                    <span>{session.totalLatency.toFixed(2)}s</span>
                </span>
            </div>
        </button>
    )
}
