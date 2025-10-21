import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

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
            <div className="mb-3">
                <strong>A few things to note:</strong>
                <ul className="list-disc ml-4 mt-1 space-y-1">
                    <li>Some filters may not yet be supported, but we're working on expanding coverage.</li>
                    <li>
                        We use smart approximation techniques to keep performance high, and we aim for less than 1%
                        difference compared to exact results.
                    </li>
                    <li>
                        You can toggle the engine on or off directly from the Web Analytics interface if you want to
                        compare results or prefer the previous method.
                    </li>
                    <li>Results are currently tied to UTC timezone for query and display.</li>
                </ul>
            </div>

            <div className="mb-3">
                <strong>Coming soon:</strong>
                <ul className="list-disc ml-4 mt-1 space-y-1">
                    <li>Use the new engine for chart visualizations</li>
                    <li>Further improvements in accuracy</li>
                    <li>More filters!</li>
                </ul>
            </div>

            <p className="mb-3">
                <strong>Note:</strong> This setting is mandatory if you wish to enable the Web Analytics API.
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.WebAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSwitch
                    checked={useWebAnalyticsPreAggregatedTables}
                    onChange={(newValue) => setUseWebAnalyticsPreAggregatedTables(newValue)}
                />
            </AccessControlAction>
            <div className="mt-4">
                <AccessControlAction
                    resourceType={AccessControlResourceType.WebAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        onClick={() => handleChange(useWebAnalyticsPreAggregatedTables)}
                        disabledReason={
                            useWebAnalyticsPreAggregatedTables === savedSetting ? 'No changes to save' : undefined
                        }
                    >
                        Save
                    </LemonButton>
                </AccessControlAction>
            </div>
        </>
    )
}
