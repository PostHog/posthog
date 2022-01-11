import React from 'react'
import { useValues } from 'kea'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { UsageDisabledWarning } from './UsageDisabledWarning'
import { EventTableType, VolumeTable } from './VolumeTable'
import { DefinitionDrawer } from 'scenes/LEGACY_events/definitions/DefinitionDrawer'
import { SceneExport } from 'scenes/sceneTypes'
import { EventsTab } from 'scenes/LEGACY_events/EventsTabs'
import { EventPageHeader } from './EventPageHeader'

export const scene: SceneExport = {
    component: EventsVolumeTable,
    logic: eventDefinitionsModel,
}

export function EventsVolumeTable(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { eventDefinitions, loaded } = useValues(eventDefinitionsModel)

    return (
        <div data-attr="manage-events-table">
            <EventPageHeader activeTab={EventsTab.EventsStats} />
            {loaded ? (
                <>
                    {preflight && !preflight?.is_event_property_usage_enabled ? (
                        <UsageDisabledWarning tab="Events Stats" />
                    ) : (
                        (eventDefinitions.length === 0 || eventDefinitions[0].volume_30_day === null) && (
                            <>
                                <Alert
                                    type="warning"
                                    message="We haven't been able to get usage and volume data yet. Please check later."
                                />
                            </>
                        )
                    )}
                    <VolumeTable data={eventDefinitions} type={EventTableType.Event} />
                </>
            ) : (
                <Skeleton active paragraph={{ rows: 5 }} />
            )}
            <DefinitionDrawer />
        </div>
    )
}
