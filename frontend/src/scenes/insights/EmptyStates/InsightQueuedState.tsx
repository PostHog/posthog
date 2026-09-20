import './EmptyStates.scss'

import clsx from 'clsx'

/**
 * A dashboard tile that is waiting for a free slot, not running yet. Without this the person reads a
 * running spinner and cannot tell why the tile makes no progress.
 */
export function InsightQueuedState({
    renderEmptyStateAsSkeleton = false,
}: {
    renderEmptyStateAsSkeleton?: boolean
}): JSX.Element {
    return (
        <div
            data-attr="insight-queued-state"
            className={clsx('flex flex-col gap-1 rounded px-4 py-6 w-full h-full', {
                'justify-center items-center': !renderEmptyStateAsSkeleton,
                'insights-loading-state justify-start': renderEmptyStateAsSkeleton,
            })}
        >
            <span className={clsx('font-semibold mb-1', renderEmptyStateAsSkeleton ? 'text-start' : 'text-center')}>
                Waiting to load
            </span>
            <p
                className={clsx(
                    'text-xs text-secondary m-0 max-w-120',
                    renderEmptyStateAsSkeleton ? 'text-start' : 'text-center'
                )}
            >
                The dashboard loads a few tiles at a time. This one starts as soon as a slot opens up.
            </p>
        </div>
    )
}
