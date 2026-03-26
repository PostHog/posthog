import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { DataPipelinesHogFunctions } from './DataPipelinesHogFunctions'
import { webScriptsSceneLogic } from './webScriptsSceneLogic'

export const scene: SceneExport = {
    component: WebScriptsScene,
    logic: webScriptsSceneLogic,
    productKey: ProductKey.SITE_APPS,
}

export function WebScriptsScene(): JSX.Element {
    const { activeTab } = useValues(webScriptsSceneLogic)
    const { setActiveTab } = useActions(webScriptsSceneLogic)

    const action = (
        <AppShortcut
            name="NewPipelineApp"
            keybind={[keyBinds.new]}
            intent="New JS snippet"
            interaction="click"
            scope={Scene.WebScripts}
        >
            <LemonButton
                type="primary"
                to={urls.webScriptsNew()}
                icon={<IconPlusSmall />}
                size="small"
                tooltip="New web script"
                data-attr="new-web-script"
            >
                New web script
            </LemonButton>
        </AppShortcut>
    )

    const tabs = [
        {
            key: 'all',
            label: 'All web scripts',
            content: <DataPipelinesHogFunctions kind="site_app" action={action} />,
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
                name={sceneConfigurations[Scene.WebScripts].name}
                description={sceneConfigurations[Scene.WebScripts].description}
                resourceType={{
                    type: sceneConfigurations[Scene.WebScripts].iconType || 'default_icon_type',
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
