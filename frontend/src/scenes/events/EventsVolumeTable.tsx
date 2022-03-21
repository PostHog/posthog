import React from 'react'
import { useValues, BindLogic } from 'kea'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { UsageDisabledWarning } from './UsageDisabledWarning'
import { VolumeTable } from './VolumeTable'
import { DefinitionDrawer } from 'scenes/events/definitions/DefinitionDrawer'
import { SceneExport } from 'scenes/sceneTypes'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { EventDefinitionsTable } from 'scenes/data-management/events/EventDefinitionsTable'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { DataManagementPageHeader } from 'scenes/data-management/DataManagementPageHeader'

export const scene: SceneExport = {
    component: EventsVolumeTable,
    logic: eventDefinitionsModel,
}

export function EventsVolumeTable(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { eventDefinitions, loaded } = useValues(eventDefinitionsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div data-attr="manage-events-table">
            <DataManagementPageHeader activeTab={DataManagementTab.EventDefinitions} />
            {featureFlags[FEATURE_FLAGS.DATA_MANAGEMENT] ? (
                <>
                    {preflight && !preflight?.is_event_property_usage_enabled ? (
                        <UsageDisabledWarning tab="Event Definitions" />
                    ) : (
                        (eventDefinitions.length === 0 || eventDefinitions[0].volume_30_day === null) && (
                            <>
                                <Alert
                                    type="warning"
                                    message="We haven't been able to get usage and volume data yet. Please check later."
                                    style={{ marginBottom: '1rem' }}
                                />
                            </>
                        )
                    )}
                    <BindLogic logic={eventDefinitionsTableLogic} props={{}}>
                        <EventDefinitionsTable />
                    </BindLogic>
                </>
            ) : (
                <>
                    {loaded ? (
                        <>
                            {preflight && !preflight?.is_event_property_usage_enabled ? (
                                <UsageDisabledWarning tab="Properties Stats" />
                            ) : (
                                (eventDefinitions.length === 0 || eventDefinitions[0].volume_30_day === null) && (
                                    <>
                                        <Alert
                                            type="warning"
                                            message="We haven't been able to get usage and volume data yet. Please check later."
                                            style={{ marginBottom: '1rem' }}
                                        />
                                    </>
                                )
                            )}
                            <VolumeTable data={eventDefinitions} type="event" />
                        </>
                    ) : (
                        <Skeleton active paragraph={{ rows: 5 }} />
                    )}
                </>
            )}
            {!featureFlags[FEATURE_FLAGS.DATA_MANAGEMENT] && <DefinitionDrawer />}
        </div>
    )
}
