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
import { snippetsSceneLogic } from './snippetsSceneLogic'

export const scene: SceneExport = {
    component: SnippetsScene,
    logic: snippetsSceneLogic,
    productKey: ProductKey.SITE_APPS,
}

export function SnippetsScene(): JSX.Element {
    const { activeTab } = useValues(snippetsSceneLogic)
    const { setActiveTab } = useActions(snippetsSceneLogic)

    const action = (
        <AppShortcut
            name="NewPipelineApp"
            keybind={[keyBinds.new]}
            intent="New JS snippet"
            interaction="click"
            scope={Scene.Snippets}
        >
            <LemonButton
                type="primary"
                to={urls.snippetsNew()}
                icon={<IconPlusSmall />}
                size="small"
                tooltip="New JS snippet"
                data-attr="new-snippet"
            >
                New snippet
            </LemonButton>
        </AppShortcut>
    )

    const tabs = [
        {
            key: 'all',
            label: 'All snippets',
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
                name={sceneConfigurations[Scene.Snippets].name}
                description={sceneConfigurations[Scene.Snippets].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Snippets].iconType || 'default_icon_type',
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
