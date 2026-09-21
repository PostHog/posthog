import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { DestinationsIncidentReplayBanner } from 'products/cdp/frontend/DestinationsIncidentReplayBanner'
import { destinationsEmptyState } from 'products/cdp/frontend/emptyState/destinationsEmptyState'

import { DataPipelinesHogFunctions } from './DataPipelinesHogFunctions'
import { DestinationsBatchExportsTab } from './DestinationsBatchExportsTab'
import { DestinationsNotificationsTab } from './DestinationsNotificationsTab'
import { DestinationsSceneTab, destinationsSceneLogic } from './destinationsSceneLogic'

export const scene: SceneExport = {
    component: DestinationsScene,
    logic: destinationsSceneLogic,
    productKey: ProductKey.PIPELINE_DESTINATIONS,
    emptyState: destinationsEmptyState,
}

// Each tab mounts its own list, so only the active kind of destination is fetched.
const TABS: LemonTab<DestinationsSceneTab>[] = [
    {
        key: 'realtime',
        label: 'Real-time',
        tooltip: 'Destinations that receive each event as it arrives.',
        'data-attr': 'destinations-tab-realtime',
        content: <DataPipelinesHogFunctions kind="destination" additionalKinds={['site_destination']} />,
    },
    {
        key: 'batch',
        label: 'Batch exports',
        tooltip: 'Destinations that receive data on a schedule, such as a warehouse or a storage bucket.',
        'data-attr': 'destinations-tab-batch',
        content: <DestinationsBatchExportsTab />,
    },
    {
        key: 'notifications',
        label: 'Notifications',
        tooltip: 'Destinations for the alerts and other events that PostHog itself sends.',
        'data-attr': 'destinations-tab-notifications',
        content: <DestinationsNotificationsTab />,
    },
    {
        key: 'history',
        label: 'History',
        'data-attr': 'destinations-tab-history',
        content: <ActivityLog scope={[ActivityScope.HOG_FUNCTION, ActivityScope.BATCH_EXPORT]} />,
    },
]

export function DestinationsScene(): JSX.Element {
    const { activeTab } = useValues(destinationsSceneLogic)
    const { setActiveTab } = useActions(destinationsSceneLogic)

    const action = (
        <Shortcut
            name="NewPipelineDestination"
            keybind={[keyBinds.new]}
            intent="New destination"
            interaction="click"
            scope={Scene.Destinations}
        >
            <LemonButton
                type="primary"
                to={urls.dataPipelinesNew('destination')}
                icon={<IconPlusSmall />}
                size="small"
                tooltip="New destination"
                data-attr="new-destination"
            >
                New destination
            </LemonButton>
        </Shortcut>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Destinations].name}
                description={sceneConfigurations[Scene.Destinations].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Destinations].iconType || 'default_icon_type',
                }}
                actions={action}
            />
            <DestinationsIncidentReplayBanner />
            <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={TABS} sceneInset />
        </SceneContent>
    )
}
