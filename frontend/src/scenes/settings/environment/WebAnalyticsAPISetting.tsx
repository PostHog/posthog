import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

export function WebAnalyticsEnablePreAggregatedTables(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <div>
            <LemonSwitch
                checked={!!currentTeam?.web_analytics_pre_aggregated_tables_enabled}
                onChange={(enabled) => updateCurrentTeam({ web_analytics_pre_aggregated_tables_enabled: enabled })}
                disabled={currentTeamLoading}
                label="Enable new query engine"
            />
            <div className="text-muted mt-2 text-sm max-w-160">
                When enabled, this project will use the new optimized query engine for web analytics whenever possible.
            </div>
        </div>
    )
}
