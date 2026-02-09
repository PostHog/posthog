import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { DataModelingTab } from '../data-warehouse/scene/DataModelingTab'

export const scene: SceneExport = {
    component: ModelsScene,
    productKey: ProductKey.DATA_WAREHOUSE_SAVED_QUERY,
}

export function ModelsScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Models].name}
                description={sceneConfigurations[Scene.Models].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Models].iconType || 'default_icon_type',
                }}
                actions={
                    <div className="flex gap-2">
                        <AppShortcut
                            name="NewModel"
                            keybind={[keyBinds.new]}
                            intent="New view"
                            interaction="click"
                            scope={Scene.Models}
                        >
                            <LemonButton
                                type="primary"
                                to={urls.sqlEditor()}
                                size="small"
                                tooltip="Create view"
                                data-attr="new-view-button"
                            >
                                Create view
                            </LemonButton>
                        </AppShortcut>
                    </div>
                }
            />
            <DataModelingTab />
        </SceneContent>
    )
}
