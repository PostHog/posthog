import { useActions, useValues } from 'kea'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { ConcreteLemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { DefinitionsSceneTabs } from 'scenes/data-management/DefinitionsSceneTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    WarehouseGroupPropertiesSetting,
    WarehousePersonPropertiesSetting,
} from '../CustomerAnalyticsConfigurationScene/account/WarehousePersonPropertiesSetting'
import { WarehousePropertiesSceneTab, warehousePropertiesSceneLogic } from './warehousePropertiesSceneLogic'

export const scene: SceneExport = {
    component: WarehousePropertiesScene,
    logic: warehousePropertiesSceneLogic,
}

export function WarehousePropertiesScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { currentTab } = useValues(warehousePropertiesSceneLogic)
    const { setCurrentTab } = useActions(warehousePropertiesSceneLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES]) {
        return <NotFound object="page" caption="Warehouse properties isn't available for this project yet." />
    }

    const tabs: ConcreteLemonTab<WarehousePropertiesSceneTab>[] = [
        {
            label: 'Persons',
            key: 'persons',
            content: <WarehousePersonPropertiesSetting />,
        },
    ]

    // Groups need the paid feature and at least one group type, so hide the tab rather than show a
    // table nothing can be added to.
    if (groupsEnabled) {
        tabs.push({
            label: 'Groups',
            key: 'groups',
            content: <WarehouseGroupPropertiesSetting />,
        })
    }

    return (
        <QuillSurfaceContext.Provider value={todayRailNav}>
            <SceneContent>
                <DefinitionsSceneTabs activeKey="warehouse-properties" />
                <SceneTitleSection
                    name="Warehouse properties"
                    description="Add properties to your people and groups from a data warehouse table. Each row is matched by a key column, then the mapped columns stay up to date on every sync."
                    resourceType={{ type: 'data_warehouse' }}
                />
                {todayRailNav ? (
                    <Tabs value={currentTab} onValueChange={(tab) => setCurrentTab(tab as WarehousePropertiesSceneTab)}>
                        <TabsList variant="line">
                            {tabs.map((tab) => (
                                <TabsTrigger key={tab.key} value={tab.key}>
                                    {tab.label}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                        {tabs.map((tab) => (
                            <TabsContent key={tab.key} value={tab.key}>
                                {tab.content}
                            </TabsContent>
                        ))}
                    </Tabs>
                ) : (
                    <LemonTabs activeKey={currentTab} onChange={setCurrentTab} tabs={tabs} sceneInset />
                )}
            </SceneContent>
        </QuillSurfaceContext.Provider>
    )
}
