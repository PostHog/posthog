import React from 'react'
import { useValues } from 'kea'
import { VolumeTable, UsageDisabledWarning } from './EventsVolumeTable'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { propertyDefinitionsLogic } from './propertyDefinitionsLogic'

export function PropertiesVolumeTable(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { propertyDefinitions, loaded } = useValues(propertyDefinitionsLogic)

    return loaded ? (
        <>
            {preflight && !preflight?.is_event_property_usage_enabled ? (
                <UsageDisabledWarning tab="Properties Stats" />
            ) : (
                propertyDefinitions[0].volume_30_day === null && (
                    <>
                        <Alert
                            type="warning"
                            message="We haven't been able to get usage and volume data yet. Please check back later."
                        />
                    </>
                )
            )}
            <VolumeTable data={propertyDefinitions} type="property" />
        </>
    ) : (
        <Skeleton active paragraph={{ rows: 5 }} />
    )
}
