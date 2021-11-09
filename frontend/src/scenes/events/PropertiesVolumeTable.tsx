import React from 'react'
import { useValues } from 'kea'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PageHeader } from 'lib/components/PageHeader'
import { UsageDisabledWarning } from './UsageDisabledWarning'
import { VolumeTable } from './VolumeTable'
import { DefinitionDrawer } from 'scenes/events/definitions/DefinitionDrawer'
import { SceneExport } from 'scenes/sceneTypes'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { EventsTab, EventsTabs } from 'scenes/events/EventsTabs'

export const scene: SceneExport = {
    component: PropertiesVolumeTable,
    logic: eventDefinitionsModel,
}

export function PropertiesVolumeTable(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { propertyDefinitions, loaded } = useValues(propertyDefinitionsModel)

    return (
        <div data-attr="manage-events-table" style={{ paddingTop: 32 }}>
            <EventsTabs tab={EventsTab.EventPropertyStats} />
            <PageHeader
                title="Properties Stats"
                caption="See all property keys that have ever been sent to this team, including the volume and how often
                queries where made using this property key."
                style={{ marginTop: 0 }}
            />
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
