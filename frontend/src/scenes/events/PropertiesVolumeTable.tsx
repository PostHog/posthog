import React from 'react'
import { BindLogic, useValues } from 'kea'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { UsageDisabledWarning } from './UsageDisabledWarning'
import { VolumeTable } from './VolumeTable'
import { DefinitionDrawer } from 'scenes/events/definitions/DefinitionDrawer'
import { SceneExport } from 'scenes/sceneTypes'
import { DataManagementPageHeader } from 'scenes/data-management/DataManagementPageHeader'
import { DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventPropertyDefinitionsTableLogic } from 'scenes/data-management/event-properties/eventPropertyDefinitionsTableLogic'
import { EventPropertyDefinitionsTable } from 'scenes/data-management/event-properties/EventPropertyDefinitionsTable'

export const scene: SceneExport = {
    component: PropertiesVolumeTable,
    logic: propertyDefinitionsModel,
}

export function PropertiesVolumeTable(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { propertyDefinitions, loaded } = useValues(propertyDefinitionsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div data-attr="manage-events-table">
            <DataManagementPageHeader activeTab={DataManagementTab.EventPropertyDefinitions} />
            {featureFlags[FEATURE_FLAGS.DATA_MANAGEMENT] ? (
                <>
                    {preflight && !preflight?.is_event_property_usage_enabled ? (
                        <UsageDisabledWarning tab="Event Property Definitions" />
                    ) : (
                        propertyDefinitions.length === 0 ||
                        (propertyDefinitions[0].query_usage_30_day === null && (
                            <>
                                <Alert
                                    type="warning"
                                    message="We haven't been able to get usage and volume data yet. Please check back later."
                                    style={{ marginBottom: '1rem' }}
                                />
                            </>
                        ))
                    )}
                    <BindLogic logic={eventPropertyDefinitionsTableLogic} props={{}}>
                        <EventPropertyDefinitionsTable />
                    </BindLogic>
                </>
            ) : (
                <>
                    {loaded ? (
                        <>
                            {preflight && !preflight?.is_event_property_usage_enabled ? (
                                <UsageDisabledWarning tab="Properties Stats" />
                            ) : (
                                propertyDefinitions.length === 0 ||
                                (propertyDefinitions[0].query_usage_30_day === null && (
                                    <>
                                        <Alert
                                            type="warning"
                                            message="We haven't been able to get usage and volume data yet. Please check back later."
                                            style={{ marginBottom: '1rem' }}
                                        />
                                    </>
                                ))
                            )}
                            <VolumeTable data={propertyDefinitions} type="property" />
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
