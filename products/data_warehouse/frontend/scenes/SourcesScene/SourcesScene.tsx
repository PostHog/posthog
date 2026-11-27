import { useActions, useValues } from 'kea'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WarehouseAlertsSection } from 'products/data_warehouse/frontend/shared/alerts/WarehouseAlertsSection'

import { dataWarehouseEmptyState } from '../../emptyState/dataWarehouseEmptyState'
import { SourcesList } from './SourcesList'
import { SourcesSceneTab, sourcesSceneLogic } from './sourcesSceneLogic'

export const scene: SceneExport = {
    component: SourcesScene,
    logic: sourcesSceneLogic,
    productKey: ProductKey.DATA_WAREHOUSE,
    emptyState: dataWarehouseEmptyState,
}

export function SourcesScene(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const alertsEnabled = useFeatureFlag('PLATFORM_ALERTS_SOURCE_WAREHOUSE')
    const { activeTab } = useValues(sourcesSceneLogic)
    const { setActiveTab } = useActions(sourcesSceneLogic)
    const action = (
        <Shortcut
            name="NewPipelineSource"
            keybind={[keyBinds.new]}
            intent="New source"
            interaction="click"
            scope={Scene.Sources}
        >
            {todayRailNav ? (
                <Button
                    variant="primary"
                    render={<LinkPrimitive to={urls.dataPipelinesNew('source')} />}
                    tooltip="New source"
                    data-attr="new-source"
                >
                    <IconPlus />
                    New source
                </Button>
            ) : (
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
            )}
        </Shortcut>
    )

    const tabs: LemonTab<SourcesSceneTab>[] = [
        { key: 'sources', label: 'Sources', content: <SourcesList /> },
        {
            key: 'alerts',
            label: 'Alerts',
            content: <WarehouseAlertsSection kind="warehouse_source" entry="sources_page" />,
        },
    ]

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name={sceneConfigurations[Scene.Sources].name}
                description={sceneConfigurations[Scene.Sources].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Sources].iconType || 'default_icon_type',
                }}
                actions={action}
            />
            {alertsEnabled ? (
                <LemonTabs activeKey={activeTab} onChange={(key) => setActiveTab(key)} tabs={tabs} sceneInset />
            ) : (
                <SourcesList />
            )}
        </SceneContent>
    )
}
