import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonSwitch } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { teamLogic } from 'scenes/teamLogic'

export function WebAnalyticsEnablePreAggregatedTables(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedSetting = currentTeam?.web_analytics_pre_aggregated_tables_enabled
    const [enableNewQueryEngine, setEnableNewQueryEngine] = useState<boolean>(savedSetting ?? false)

    const handleSave = (): void => {
        updateCurrentTeam({ web_analytics_pre_aggregated_tables_enabled: enableNewQueryEngine })
    }

    return (
        <>
            <p>
                When enabled, this project will use the new query engine for Web Analytics whenever possible. This
                setting is mandatory if you wish to enable the Web Analytics API.
            </p>
            <LemonSwitch checked={enableNewQueryEngine} onChange={(enabled) => setEnableNewQueryEngine(enabled)} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabledReason={enableNewQueryEngine === savedSetting ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
