import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ActionsTable } from '../components/ActionsTable'
import { NewActionButton } from '../components/NewActionButton'
import { actionsLogic } from '../logics/actionsLogic'

export const scene: SceneExport = {
    component: Actions,
    logic: actionsLogic,
}

export function Actions(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Actions].name}
                description={sceneConfigurations[Scene.Actions].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Actions].iconType || 'default_icon_type',
                }}
                actions={<NewActionButton />}
            />
            <ActionsTable />
        </SceneContent>
    )
}
