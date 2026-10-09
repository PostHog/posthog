import { useValues } from 'kea'

import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'

/** The limits of the project, read-only. PostHog sets them, so there is nothing to edit here. */
export function TeamLimits(): JSX.Element | null {
    const { limits } = useValues(cloudAgentsCatalogLogic)
    if (!limits) {
        return null
    }
    return (
        <div className="text-secondary flex flex-wrap gap-x-6 gap-y-1 text-xs" data-attr="cloud-agents-team-limits">
            <span>
                Runs in progress at one time:{' '}
                <span className="text-primary font-semibold" translate="no">
                    {limits.max_concurrent_runs}
                </span>
            </span>
            <span>
                New runs per hour:{' '}
                <span className="text-primary font-semibold" translate="no">
                    {limits.create_rate_per_hour}
                </span>
            </span>
            <span>Contact support to raise a limit.</span>
        </div>
    )
}
