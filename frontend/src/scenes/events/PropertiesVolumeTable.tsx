import React from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { VolumeTable, UsageDisabledWarning } from './EventsVolumeTable'
import { Alert } from 'antd'

export function PropertiesVolumeTable(): JSX.Element | null {
    const { user } = useValues(userLogic)
    return user?.team?.event_properties_with_usage ? (
        <>
            {!user?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning tab="Properties Stats" />
            ) : (
                user?.team?.event_properties_with_usage[0]?.volume === null && (
                    <>
                        <Alert
                            type="warning"
                            message="We haven't been able to get usage and volume data yet. Please check back later"
                        />
                    </>
                )
            )}
            <VolumeTable data={user?.team?.event_properties_with_usage} type="key" />
        </>
    ) : null
}
