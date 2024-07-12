import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehouseSettingsTab } from '~/types'

import {
    dataWarehouseSourceSettingsLogic,
    DataWarehouseSourceSettingsLogicProps,
    DataWarehouseSourceSettingsTabs,
} from './dataWarehouseSourceSettingsLogic'
import { Schemas } from './Schemas'
import { Syncs } from './Syncs'

const paramsToProps = ({
    params: { id, tab },
}: {
    params: { id?: string; tab?: string }
}): DataWarehouseSourceSettingsLogicProps => {
    if (!id || !tab) {
        throw new Error('Loaded DataWarehouseSourceSettings without eother `id` or `tab`')
    }

    return {
        id,
        parentSettingsTab: tab as DataWarehouseSettingsTab,
    }
}

export const scene: SceneExport = {
    component: DataWarehouseSourceSettingsScene,
    logic: dataWarehouseSourceSettingsLogic,
    paramsToProps,
}

const TabContent: Record<DataWarehouseSourceSettingsTabs, () => JSX.Element> = {
    [DataWarehouseSourceSettingsTabs.Schemas]: Schemas,
    [DataWarehouseSourceSettingsTabs.Syncs]: Syncs,
}

const FriendlyTabNames: Record<DataWarehouseSourceSettingsTabs, string> = {
    [DataWarehouseSourceSettingsTabs.Schemas]: 'Schemas',
    [DataWarehouseSourceSettingsTabs.Syncs]: 'Syncs',
}

export function DataWarehouseSourceSettingsScene(): JSX.Element {
    const { parentSettingsTab, currentTab } = useValues(dataWarehouseSourceSettingsLogic)
    const { setCurrentTab } = useActions(dataWarehouseSourceSettingsLogic)

    return (
        <div>
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.dataWarehouseSettings(parentSettingsTab)}>
                        Cancel
                    </LemonButton>
                }
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => setCurrentTab(tab as DataWarehouseSourceSettingsTabs)}
                tabs={Object.entries(TabContent).map(([tab, ContentComponent]) => ({
                    label: FriendlyTabNames[tab],
                    key: tab,
                    content: <ContentComponent />,
                }))}
            />
        </div>
    )
}
