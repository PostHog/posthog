import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

export function PreAggregatedTablesSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedSetting = currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables
    const [useWebAnalyticsPreAggregatedTables, setUseWebAnalyticsPreAggregatedTables] = useState<boolean>(
        savedSetting ?? false
    )

    const handleChange = (mode: boolean): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, useWebAnalyticsPreAggregatedTables: mode } })
    }

    return (
        <>
            <p>
                Choose whether to use pre-aggregated tables for Web Analytics queries. Pre-aggregated tables can
                significantly improve query performance, but like sampling, may have slight differences in results
                compared to querying raw event data.
            </p>
            <LemonSwitch
                checked={useWebAnalyticsPreAggregatedTables}
                onChange={(newValue) => setUseWebAnalyticsPreAggregatedTables(newValue)}
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(useWebAnalyticsPreAggregatedTables)}
                    disabledReason={
                        useWebAnalyticsPreAggregatedTables === savedSetting ? 'No changes to save' : undefined
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
