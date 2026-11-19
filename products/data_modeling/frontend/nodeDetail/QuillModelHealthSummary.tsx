import { Badge, Button, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { STATUS_TOOLTIPS } from '../lineage/nodeStyles'
import type { ModelHealthSummaryProps } from './ModelHealthSummary'
import { QuillModelDownstreamSummary } from './QuillModelDownstreamSummary'
import { QuillModelErrorText } from './QuillModelErrorText'
import { QuillModelFact } from './QuillModelFact'
import { QuillModelFacts } from './QuillModelFacts'
import { QuillModelSummaryCard } from './QuillModelSummaryCard'
import { RUN_STATUS_BADGE_VARIANTS, runStatusLabel } from './quillNodeDetailBadges'

function healthTitle(suspended: boolean, status: string | null): string {
    if (suspended) {
        return 'Scheduled refreshes'
    }
    if (status === 'Running') {
        return 'Current run'
    }
    return status === 'Modified' ? 'Status' : 'Last run'
}

function StatusBadge({ status, suspended }: { status: string; suspended: boolean }): JSX.Element {
    const badge = (
        <Badge variant={suspended ? 'destructive' : (RUN_STATUS_BADGE_VARIANTS[status] ?? 'default')}>
            {suspended ? 'Suspended' : runStatusLabel(status)}
        </Badge>
    )
    const explanation = suspended ? undefined : STATUS_TOOLTIPS[status]
    if (!explanation) {
        return badge
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<span tabIndex={0} />}>{badge}</TooltipTrigger>
            <TooltipContent>{explanation}</TooltipContent>
        </Tooltip>
    )
}

export function QuillModelHealthSummary({
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
    return (
        <QuillModelSummaryCard metadata={metadata} dataAttr="node-detail-health">
            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" weight="semibold" render={<span />}>
                    {healthTitle(suspended, status)}
                </Text>
                {status || suspended ? (
                    <StatusBadge status={status ?? ''} suspended={suspended} />
                ) : historyError ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        Status unavailable
                    </Text>
                ) : historyLoaded ? (
                    <Badge>Not run yet</Badge>
                ) : (
                    <Skeleton className="h-5 w-20" />
                )}
            </div>
            {(suspended || status === 'Failed') && error && <QuillModelErrorText error={error} />}
            {suspended && (
                <Text size="xs" variant="muted" className="m-0">
                    Fix the query, then use Sync now. It clears the suspension before the run starts, so this model goes
                    back on its schedule even if the run fails.
                </Text>
            )}
            {historyError && (
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="xs" variant="muted" render={<span />}>
                        Couldn't refresh run status. Retrying automatically.
                    </Text>
                    {onRetry && (
                        <Button variant="outline" size="sm" onClick={onRetry} loading={retryLoading}>
                            Retry now
                        </Button>
                    )}
                </div>
            )}
            <QuillModelFacts>
                <QuillModelFact label="Last successful refresh">
                    {lastSuccessfulSyncAt ? (
                        <TZLabel time={lastSuccessfulSyncAt} />
                    ) : historyError ? (
                        'Run history unavailable'
                    ) : historyLoaded ? (
                        'No successful run in recent history'
                    ) : (
                        <Skeleton className="h-4 w-32" />
                    )}
                </QuillModelFact>
                <QuillModelFact
                    label="Refresh schedule"
                    hint="How often this view refreshes, including pauses and suspension. A downstream view can make it refresh more often than its own setting."
                >
                    {schedule ?? <Skeleton className="h-4 w-32" />}
                </QuillModelFact>
                <QuillModelDownstreamSummary
                    downstreamCount={downstreamCount}
                    lineageUrl={lineageUrl}
                    loading={schedule === null || (!historyLoaded && !historyError)}
                />
            </QuillModelFacts>
        </QuillModelSummaryCard>
    )
}
