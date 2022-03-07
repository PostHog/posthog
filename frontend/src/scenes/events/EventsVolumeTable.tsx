import React from 'react'
import { useValues, BindLogic } from 'kea'
import { Alert, Skeleton } from 'antd'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { UsageDisabledWarning } from './UsageDisabledWarning'
import { VolumeTable } from './VolumeTable'
import { DefinitionDrawer } from 'scenes/events/definitions/DefinitionDrawer'
import { SceneExport } from 'scenes/sceneTypes'
import { EventsTab } from 'scenes/events/EventsTabs'
import { EventPageHeader } from './EventPageHeader'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { EventDefinitionsTable } from 'scenes/data-management/events/EventDefinitionsTable'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'

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
            <EventPageHeader activeTab={EventsTab.EventStats} />
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
                    {featureFlags[FEATURE_FLAGS.COLLABORATIONS_TAXONOMY] ? (
                        <BindLogic logic={eventDefinitionsTableLogic} props={{ syncWithUrl: true }}>
                            <EventDefinitionsTable />
                        </BindLogic>
                    ) : (
                        <VolumeTable data={eventDefinitions} type="event" />
                    )}
                </>
            ) : (
                <Skeleton active paragraph={{ rows: 5 }} />
            )}
            {!featureFlags[FEATURE_FLAGS.COLLABORATIONS_TAXONOMY] && <DefinitionDrawer />}
        </div>
    )
}
