import { IconBell, IconCheck, IconInfo } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, Spinner, Text, cn } from '@posthog/quill'

import { useRetryCountdownLabel } from '~/scenes/experiments/MetricsView/shared/MetricRetryState'
import { Experiment } from '~/types'

import { QuillHelpTooltip } from '../../ExperimentView/QuillCardParts'
import {
    ClimbingRows,
    RECALCULATION_AGE_LIMIT_NOTE,
    RECALCULATION_BACKGROUND_HELP,
    RECALCULATION_NOTICE_NOTE,
    pendingMetricCount,
    useRecalculationStatus,
} from './RecalculationStatus'

function Count({ value, label, className }: { value: number; label: string; className?: string }): JSX.Element {
    return (
        <span className={cn('whitespace-nowrap font-medium', className)}>
            {value} {label}
        </span>
    )
}

function Muted({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
            {children}
        </Text>
    )
}

export function QuillRecalculationStatus({
    experiment,
    className,
}: {
    experiment: Experiment
    className?: string
}): JSX.Element | null {
    const status = useRecalculationStatus(experiment)
    const nextRetryLabel = useRetryCountdownLabel(status.nextRetryAt)

    if (!status.inFlight) {
        if (!status.provenance) {
            return null
        }
        return (
            <Item
                variant="outline"
                size="sm"
                tone="info"
                className={className}
                data-attr="experiment-results-configuration-notice"
            >
                <ItemMedia variant="icon" aria-hidden>
                    <IconInfo />
                </ItemMedia>
                <ItemContent className="min-w-0">
                    <ItemDescription className="line-clamp-none">
                        {status.provenance}{' '}
                        {status.ageLimitExceeded ? RECALCULATION_AGE_LIMIT_NOTE : RECALCULATION_NOTICE_NOTE}
                    </ItemDescription>
                </ItemContent>
                {!status.ageLimitExceeded && (
                    <ItemActions>
                        <Button
                            variant="outline"
                            onClick={status.recalculate}
                            loading={status.isRecalculating}
                            disabledReason={status.recalculateDisabledReason}
                        >
                            Recalculate
                        </Button>
                    </ItemActions>
                )}
            </Item>
        )
    }

    const { recalculation, retryingCount, liveRowsProgress } = status
    const succeeded = recalculation?.completed_metrics ?? 0
    const failed = recalculation?.failed_metrics ?? 0
    const pending = pendingMetricCount(recalculation, retryingCount)
    const counts = [
        pending > 0 && <Count key="pending" value={pending} label="pending" />,
        retryingCount > 0 && (
            <Count key="retrying" value={retryingCount} label="retrying" className="text-warning-foreground" />
        ),
        <Count key="succeeded" value={succeeded} label="succeeded" className="text-success-foreground" />,
        failed > 0 && <Count key="failed" value={failed} label="failed" className="text-destructive-foreground" />,
    ].filter(Boolean)

    return (
        <Item variant="outline" size="sm" className={className} data-attr="experiment-recalculation-status">
            <ItemMedia variant="icon" aria-hidden>
                <Spinner />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
                    {counts.map((count, index) => (
                        <span key={index} className="flex items-center gap-1.5">
                            {index > 0 && <span>·</span>}
                            {count}
                        </span>
                    ))}
                    {retryingCount > 0 && <Muted>· next retry {nextRetryLabel}</Muted>}
                    <Muted>· running in the background</Muted>
                    <QuillHelpTooltip label="recalculation" help={RECALCULATION_BACKGROUND_HELP} />
                    {liveRowsProgress && liveRowsProgress.recalculationId === recalculation?.id && (
                        <ClimbingRows
                            rowsRead={liveRowsProgress.rowsRead}
                            estimatedRows={liveRowsProgress.estimatedRows || undefined}
                            className="whitespace-nowrap text-xs text-muted-foreground"
                        />
                    )}
                </span>
            </ItemContent>
            <ItemActions>
                {status.notifyWhenResultsReady ? (
                    <Button variant="outline" disabledReason="Keep this tab open to get notified">
                        <IconCheck />
                        We'll notify you
                    </Button>
                ) : (
                    <Button variant="outline" onClick={status.subscribe} data-attr="experiment-results-notify">
                        <IconBell />
                        Notify me
                    </Button>
                )}
            </ItemActions>
        </Item>
    )
}
