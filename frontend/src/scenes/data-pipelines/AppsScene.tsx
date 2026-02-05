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
import { appsSceneLogic } from './appsSceneLogic'

export const scene: SceneExport = {
    component: AppsScene,
    logic: appsSceneLogic,
    productKey: ProductKey.SITE_APPS,
}

export function AppsScene(): JSX.Element {
    const { activeTab } = useValues(appsSceneLogic)
    const { setActiveTab } = useActions(appsSceneLogic)

    const action = (
        <AppShortcut
            name="NewPipelineApp"
            keybind={[keyBinds.new]}
            intent="New app"
            interaction="click"
            scope={Scene.Apps}
        >
            <LemonButton
                type="primary"
                to={urls.appsNew()}
                icon={<IconPlusSmall />}
                size="small"
                tooltip="New app"
                data-attr="new-app"
            >
                New app
            </LemonButton>
        </AppShortcut>
    )

    const tabs = [
        {
            key: 'all',
            label: 'All apps',
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
                name={sceneConfigurations[Scene.Apps].name}
                description={sceneConfigurations[Scene.Apps].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Apps].iconType || 'default_icon_type',
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
