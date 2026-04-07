import { IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'

import { LegacyErrorChecklist } from './LegacyErrorChecklist'

interface LegacyChartEmptyStateProps {
    height: number
    experimentStarted: boolean
    metric: ExperimentTrendsQuery | ExperimentFunnelsQuery
    error?: any
}

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * For new experiments, use the modern ChartEmptyState component.
 */
export function LegacyChartEmptyState({
    height,
    experimentStarted,
    error,
    metric,
}: LegacyChartEmptyStateProps): JSX.Element | null {
    /**
     * early return if experiment has not started
     */
    if (!experimentStarted) {
        return (
            <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
                <LemonTag size="small" className="mr-2">
                    <IconClock fontSize="1em" />
                </LemonTag>
                <span>Waiting for experiment to start&hellip;</span>
            </div>
        )
    }

    /**
     * bail if no error
     */
    if (!error) {
        return null
    }

    /**
     * Legacy metrics always use the legacy error checklist
     */
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="flex items-center justify-center w-full" style={{ height: `${height}px` }}>
            <LegacyErrorChecklist error={error} metric={metric} />
        </div>
    )
}
