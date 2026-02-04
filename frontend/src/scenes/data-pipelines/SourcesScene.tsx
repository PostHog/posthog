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

import { DataPipelinesSources } from './DataPipelinesSources'
import { sourcesSceneLogic } from './sourcesSceneLogic'

export const scene: SceneExport = {
    component: SourcesScene,
    logic: sourcesSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
}

export function SourcesScene(): JSX.Element {
    const action = (
        <AppShortcut
            name="NewPipelineSource"
            keybind={[keyBinds.new]}
            intent="New source"
            interaction="click"
            scope={Scene.Sources}
        >
            <LemonButton
                type="primary"
                to={urls.dataPipelinesNew('source')}
                icon={<IconPlusSmall />}
                size="small"
                tooltip="New source"
                data-attr="new-source"
            >
                New source
            </LemonButton>
        </AppShortcut>
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Sources].name}
                description={sceneConfigurations[Scene.Sources].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Sources].iconType || 'default_icon_type',
                }}
                actions={action}
            />
            <DataPipelinesSources action={action} />
        </SceneContent>
    )
}
