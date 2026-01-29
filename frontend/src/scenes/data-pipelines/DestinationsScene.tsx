import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { DataPipelinesHogFunctions } from './DataPipelinesHogFunctions'
import { destinationsSceneLogic } from './destinationsSceneLogic'

export const scene: SceneExport = {
    component: DestinationsScene,
    logic: destinationsSceneLogic,
    productKey: ProductKey.PIPELINE_DESTINATIONS,
}

export function DestinationsScene(): JSX.Element {
    const { activeTab } = useValues(destinationsSceneLogic)
    const { setActiveTab } = useActions(destinationsSceneLogic)

    const action = (
        <AppShortcut
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
        </AppShortcut>
    )

    const tabs = [
        {
            key: 'all',
            label: 'All destinations',
            content: (
                <DataPipelinesHogFunctions kind="destination" additionalKinds={['site_destination']} action={action} />
            ),
        },
        {
            key: 'history',
            label: 'History',
            content: <ActivityLog scope={[ActivityScope.HOG_FUNCTION, ActivityScope.BATCH_EXPORT]} />,
        },
    ]

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
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as 'all' | 'history')}
                tabs={tabs}
                sceneInset
            />
        </SceneContent>
    )
}
