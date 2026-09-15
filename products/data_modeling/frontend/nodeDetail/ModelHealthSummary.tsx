import type { ReactNode } from 'react'

import { LemonButton, LemonTag, LemonTagType, Tooltip, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { STATUS_TOOLTIPS } from '../lineage/nodeStyles'
import { ModelDownstreamSummary } from './ModelDownstreamSummary'
import { ModelSummaryCard } from './ModelSummaryCard'

export interface ModelHealthSummaryProps {
    status: string | null
    suspended: boolean
    error?: string | null
    lastSuccessfulSyncAt: string | null
    historyLoaded: boolean
    historyError?: boolean
    onRetry?: () => void
    retryLoading?: boolean
    schedule: string | null
    lineageUrl: string
    downstreamCount: number
    metadata?: ReactNode
}

const STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    Completed: 'success',
    Failed: 'danger',
    Running: 'warning',
    Cancelled: 'muted',
    Skipped: 'muted',
    // Not a run outcome: the query was edited and has not been materialized since.
    Modified: 'warning',
}

export function ModelHealthSummary({
    status,
    suspended,
    error,
    lastSuccessfulSyncAt,
    historyLoaded,
    historyError,
    onRetry,
    retryLoading,
    schedule,
    lineageUrl,
    downstreamCount,
    metadata,
}: ModelHealthSummaryProps): JSX.Element {
    const failed = status === 'Failed'
    const statusLabel = suspended ? 'Suspended' : status === 'Cancelled' ? 'Canceled' : status
    const title = suspended
        ? 'Scheduled refreshes'
        : status === 'Running'
          ? 'Current run'
          : status === 'Modified'
            ? 'Status'
            : 'Last run'
    // A suspended model explains itself in the paragraph below, so it needs no second explanation.
    const statusExplanation = suspended ? undefined : STATUS_TOOLTIPS[status ?? '']
    return (
        <ModelSummaryCard metadata={metadata} dataAttr="node-detail-health">
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{title}</span>
                    {statusLabel ? (
                        <Tooltip title={statusExplanation}>
                            <LemonTag type={suspended ? 'danger' : (STATUS_TAG_TYPES[status ?? ''] ?? 'default')}>
                                {statusLabel}
                            </LemonTag>
                        </Tooltip>
                    ) : historyError ? (
                        <span className="text-secondary">Status unavailable</span>
                    ) : historyLoaded ? (
                        <LemonTag type="muted">Not run yet</LemonTag>
                    ) : (
                        <LemonSkeleton className="h-5 w-20" />
                    )}
                </div>
                {/* A database exception runs to as many lines as it likes, and this card sits above
                    the metadata and the tabs, so an unbounded one pushes the rest of the page out of
                    view. Bounded the way the run history bounds the same strings. */}
                {(suspended || failed) && error && (
                    <p className="mb-0 max-h-64 overflow-auto text-sm font-mono text-danger break-words whitespace-pre-wrap">
                        {error}
                    </p>
                )}
                {suspended && (
                    <p className="mb-0 text-sm text-secondary">
                        Fix the query, then use Sync now. It clears the suspension before the run starts, so this model
                        goes back on its schedule even if the run fails.
                    </p>
                )}
                {historyError && (
                    <div className="flex flex-wrap items-center gap-2 text-secondary text-sm">
                        <span>Couldn't refresh run status. Retrying automatically.</span>
                        {onRetry && (
                            <LemonButton size="xsmall" onClick={onRetry} loading={retryLoading}>
                                Retry now
                            </LemonButton>
                        )}
                    </div>
                )}
                <dl className="flex flex-wrap gap-x-10 gap-y-3 mb-0 text-sm">
                    <div>
                        <dt className="text-secondary mb-1">Last successful refresh</dt>
                        <dd className="mb-0">
                            {lastSuccessfulSyncAt ? (
                                <TZLabel time={lastSuccessfulSyncAt} />
                            ) : historyError ? (
                                'Run history unavailable'
                            ) : historyLoaded ? (
                                'No successful run in recent history'
                            ) : (
                                <LemonSkeleton className="h-4 w-32" />
                            )}
                        </dd>
                    </div>
                    <div>
                        <dt className="text-secondary mb-1">
                            <Tooltip title="The refresh schedule saved for this model, including pauses and suspension.">
                                <span className="border-b border-dashed border-secondary cursor-help">
                                    Refresh schedule
                                </span>
                            </Tooltip>
                        </dt>
                        <dd className="mb-0">{schedule ?? <LemonSkeleton className="h-4 w-32" />}</dd>
                    </div>
                    <ModelDownstreamSummary
                        downstreamCount={downstreamCount}
                        lineageUrl={lineageUrl}
                        loading={schedule === null || (!historyLoaded && !historyError)}
                    />
                </dl>
            </div>
        </ModelSummaryCard>
    )
}
