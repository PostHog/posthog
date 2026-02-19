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
