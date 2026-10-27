import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { DataCatalogMetricApi } from '../generated/api.schemas'

function runCount(count: number): string {
    return `${count} ${count === 1 ? 'run' : 'runs'}`
}

export interface AgentUsageCellProps {
    metric: DataCatalogMetricApi
    /** Agents get a warning when they run a metric that is proposed or drifted. */
    warned: boolean
    cleanupCandidate: boolean
}

export function AgentUsageCell({ metric, warned, cleanupCandidate }: AgentUsageCellProps): JSX.Element {
    if (cleanupCandidate) {
        return (
            <Tooltip title="Nobody ran this metric in the last 90 days. Delete it if your team no longer uses it.">
                <LemonTag type="muted">Not run in 90 days</LemonTag>
            </Tooltip>
        )
    }
    if (metric.ai_runs_30d === 0) {
        return <span className="text-secondary whitespace-nowrap">No runs</span>
    }
    return (
        <div className="flex flex-col">
            <Tooltip
                title={`${metric.ai_runs_30d} of ${runCount(metric.runs_30d)} in the last 30 days came from PostHog AI or other agents.`}
            >
                <span className="whitespace-nowrap">
                    {warned ? `${runCount(metric.ai_runs_30d)} with a warning` : runCount(metric.ai_runs_30d)}
                </span>
            </Tooltip>
            {warned && (
                <span className="text-xs text-secondary">
                    {/* A refresh resets the metric to proposed, so a drifted metric needs both steps. */}
                    {metric.is_drifted
                        ? 'Refresh and approve it to remove the warning.'
                        : 'Approve it to remove the warning.'}
                </span>
            )}
        </div>
    )
}
