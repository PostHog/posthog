import React from 'react'
import { useValues } from 'kea'
import { VolumeTable, UsageDisabledWarning, EventOrPropType } from './EventsVolumeTable'
import { Alert } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { teamLogic } from 'scenes/teamLogic'

export function PropertiesVolumeTable(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { preflight } = useValues(preflightLogic)
    return currentTeam?.event_properties_with_usage ? (
        <>
            {preflight && !preflight?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning tab="Properties Stats" />
            ) : (
                currentTeam?.event_properties_with_usage[0]?.volume === null && (
                    <>
                        <Alert
                            type="warning"
                            message="We haven't been able to get usage and volume data yet. Please check back later"
                        />
                    </>
                )
            )}
            <VolumeTable data={currentTeam?.event_properties_with_usage as EventOrPropType[]} type="property" />
        </>
    ) : null
}
