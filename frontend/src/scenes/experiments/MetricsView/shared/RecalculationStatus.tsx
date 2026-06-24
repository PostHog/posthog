import { useValues } from 'kea'

import { IconCheck } from '@posthog/icons'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from '~/scenes/experiments/experimentMetricsLogic'
import { ExperimentLastRefreshText } from '~/scenes/experiments/ExperimentView/ExperimentReloadAction'
import { Experiment } from '~/types'

function StatusSegment({ loading, children }: { loading: boolean; children: React.ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
            {loading ? (
                <Spinner textColored className="text-sm text-accent" />
            ) : (
                <IconCheck className="text-success text-sm" />
            )}
            {children}
        </span>
    )
}

export function RecalculationStatus({ experiment }: { experiment: Experiment }): JSX.Element {
    const { exposuresLoading } = useValues(experimentLogic)
    const { isRecalculating, recalculationProgress, lastRefresh, currentRecalculation, totalMetricsCount } = useValues(
        experimentMetricsLogic({ experiment })
    )

    const { completed, total } = recalculationProgress
    const failed = currentRecalculation?.failed_metrics ?? 0

    const metricsLabel = !isRecalculating
        ? `${totalMetricsCount} ${totalMetricsCount === 1 ? 'metric' : 'metrics'}`
        : // No run loaded yet (latest is still being fetched), so there's no real progress to show.
          total > 0
          ? `Calculating metrics ${completed}/${total}`
          : 'Loading metrics…'

    return (
        <div className="inline-flex items-center gap-2.5 rounded border border-primary bg-surface-secondary px-2.5 py-1 text-xs">
            <StatusSegment loading={isRecalculating}>
                <span className="font-medium">{metricsLabel}</span>
                {failed > 0 && <span className="text-danger font-medium">· {failed} failed</span>}
            </StatusSegment>

            <LemonDivider vertical className="h-3.5" />

            <StatusSegment loading={exposuresLoading}>
                <span>exposures</span>
            </StatusSegment>

            <LemonDivider vertical className="h-3.5" />

            {/* TZLabel hardcodes `align-middle`, which sits a few px low in this flex row; reset its span. */}
            <span className="flex items-center gap-1 whitespace-nowrap text-muted [&_span]:align-baseline">
                <span>Updated</span>
                <ExperimentLastRefreshText lastRefresh={lastRefresh} />
            </span>
        </div>
    )
}
