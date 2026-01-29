import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { DataPipelinesHogFunctions } from './DataPipelinesHogFunctions'
import { destinationsSceneLogic } from './destinationsSceneLogic'

export const scene: SceneExport = {
    component: DestinationsScene,
    logic: destinationsSceneLogic,
    productKey: ProductKey.PIPELINE_DESTINATIONS,
}

export function DestinationsScene(): JSX.Element {
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
            <DataPipelinesHogFunctions kind="destination" additionalKinds={['site_destination']} action={action} />
        </SceneContent>
    )
}
