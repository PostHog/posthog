import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    WarehouseGroupPropertiesSetting,
    WarehousePersonPropertiesSetting,
} from '../CustomerAnalyticsConfigurationScene/account/WarehousePersonPropertiesSetting'
import { WarehousePropertiesSceneTab, warehousePropertiesSceneLogic } from './warehousePropertiesSceneLogic'

type DataModelingSceneTab = 'overview' | 'models' | 'lineage' | 'data-quality' | 'property-syncs'

export const scene: SceneExport = {
    component: WarehousePropertiesScene,
    logic: warehousePropertiesSceneLogic,
}

export function WarehousePropertiesScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const { currentTab } = useValues(warehousePropertiesSceneLogic)
    const { setCurrentTab } = useActions(warehousePropertiesSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES]) {
        return <NotFound object="page" caption="Warehouse properties isn't available for this project yet." />
    }

    const profileTabs: LemonTab<WarehousePropertiesSceneTab>[] = [
        {
            label: 'Persons',
            key: 'persons',
            content: <WarehousePersonPropertiesSetting />,
        },
    ]

    // Groups need the paid feature and at least one group type, so hide the tab rather than show a
    // table nothing can be added to.
    if (groupsEnabled) {
        profileTabs.push({
            label: 'Groups',
            key: 'groups',
            content: <WarehouseGroupPropertiesSetting />,
        })
    }

    const dataModelingTabs: LemonTab<DataModelingSceneTab>[] = [
        {
            key: 'overview',
            label: 'Overview',
            link: urls.models(),
        },
        {
            key: 'models',
            label: 'Models',
            link: urls.models('models'),
        },
        {
            key: 'lineage',
            label: 'Lineage',
            link: urls.models('lineage'),
        },
        ...(featureFlags[FEATURE_FLAGS.DATA_QUALITY_CHECKS]
            ? [
                  {
                      key: 'data-quality' as const,
                      label: 'Data quality',
                      link: urls.models('data-quality'),
                  },
              ]
            : []),
        {
            key: 'property-syncs',
            label: 'Property syncs',
            link: urls.warehouseProperties(),
        },
    ]

    return (
        <SceneContent>
            <LemonTabs activeKey="property-syncs" tabs={dataModelingTabs} sceneInset className="mb-3" />
            <SceneTitleSection
                name="Warehouse properties"
                description="Add properties to your people and groups from a data warehouse table. Each row is matched by a key column, then the mapped columns stay up to date on every sync."
                resourceType={{ type: 'data_warehouse' }}
            />
            <LemonTabs activeKey={currentTab} onChange={setCurrentTab} tabs={profileTabs} sceneInset />
        </SceneContent>
    )
}
