import React from 'react'
import { useValues } from 'kea'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { UsageDisabledWarning } from './UsageDisabledWarning'
import { VolumeTable } from './VolumeTable'
import { DefinitionDrawer } from 'scenes/events/definitions/DefinitionDrawer'
import { SceneExport } from 'scenes/sceneTypes'
import { EventsTab } from 'scenes/events/EventsTabs'
import { EventPageHeader } from './EventPageHeader'

export const scene: SceneExport = {
    component: PropertiesVolumeTable,
    logic: propertyDefinitionsModel,
}

export function PropertiesVolumeTable(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { propertyDefinitions, loaded } = useValues(propertyDefinitionsModel)

    return (
        <div data-attr="manage-events-table">
            <EventPageHeader activeTab={EventsTab.EventPropertyStats} />
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
        </div>
    )
}
