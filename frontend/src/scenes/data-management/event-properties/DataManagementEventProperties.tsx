import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { dataManagementPageLogic } from 'scenes/data-management/dataManagementPageLogic'
import { DataManagementHeader } from 'scenes/data-management/DataManagementHeader'
import { UsageDisabledWarning } from 'scenes/events/UsageDisabledWarning'
import { Alert, Skeleton } from 'antd'
import { VolumeTable } from 'scenes/events/VolumeTable'
import { DefinitionDrawer } from 'scenes/events/definitions/DefinitionDrawer'
import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

export function DataManagementEventProperties(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { propertyDefinitions, loaded } = useValues(propertyDefinitionsModel)

    return (
        <>
            <DataManagementHeader />
            {loaded ? (
                <>
                    {preflight && !preflight?.is_event_property_usage_enabled ? (
                        <UsageDisabledWarning tab="Properties Stats" />
                    ) : (
                        propertyDefinitions.length === 0 ||
                        (propertyDefinitions[0].volume_30_day === null && (
                            <>
                                <Alert
                                    type="warning"
                                    message="We haven't been able to get usage and volume data yet. Please check back later."
                                />
                            </>
                        ))
                    )}
                    <VolumeTable data={propertyDefinitions} type="property" />
                </>
            ) : (
                <Skeleton active paragraph={{ rows: 5 }} />
            )}
            <DefinitionDrawer />
        </>
    )
}

export const scene: SceneExport = {
    component: DataManagementEventProperties,
    logic: dataManagementPageLogic,
}
