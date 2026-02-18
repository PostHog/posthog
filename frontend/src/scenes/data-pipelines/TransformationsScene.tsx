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
import { transformationsSceneLogic } from './transformationsSceneLogic'

export const scene: SceneExport = {
    component: TransformationsScene,
    logic: transformationsSceneLogic,
    productKey: ProductKey.PIPELINE_TRANSFORMATIONS,
}

export function TransformationsScene(): JSX.Element {
    const action = (
        <AppShortcut
            name="NewPipelineTransformation"
            keybind={[keyBinds.new]}
            intent="New transformation"
            interaction="click"
            scope={Scene.Transformations}
        >
            <LemonButton
                type="primary"
                to={urls.dataPipelinesNew('transformation')}
                icon={<IconPlusSmall />}
                size="small"
                tooltip="New transformation"
                data-attr="new-transformation"
            >
                New transformation
            </LemonButton>
        </AppShortcut>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Transformations].name}
                description={sceneConfigurations[Scene.Transformations].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Transformations].iconType || 'default_icon_type',
                }}
                actions={action}
            />
            <DataPipelinesHogFunctions kind="transformation" action={action} />
        </SceneContent>
    )
}
