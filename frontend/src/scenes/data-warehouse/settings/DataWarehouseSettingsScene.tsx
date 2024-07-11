import { LemonButton, LemonTabs } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehouseSettingsTab } from '~/types'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import { DataWarehouseManagedSourcesTable } from './DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from './DataWarehouseSelfManagedSourcesTable'
import { dataWarehouseSettingsLogic, humanFriendlyDataWarehouseSettingsTabName } from './dataWarehouseSettingsLogic'

export const scene: SceneExport = {
    component: DataWarehouseSettingsScene,
    logic: dataWarehouseSettingsLogic,
}

export function DataWarehouseSettingsScene(): JSX.Element {
    const { currentTab } = useValues(dataWarehouseSettingsLogic)

    const tabToContent: Partial<Record<DataWarehouseSettingsTab, JSX.Element>> = {
        [DataWarehouseSettingsTab.Managed]: <DataWarehouseManagedSourcesTable />,
        [DataWarehouseSettingsTab.SelfManaged]: <DataWarehouseSelfManagedSourcesTable />,
    }

    return (
        <div>
            <PageHeader
                buttons={
                    <LemonButton
                        type="primary"
                        data-attr="new-data-warehouse-easy-link"
                        key="new-data-warehouse-easy-link"
                        to={urls.dataWarehouseTable()}
                    >
                        Link source
                    </LemonButton>
                }
                caption={
                    <div>
                        Linked data sources will appear here. Data sources can take a while to sync depending on the
                        size of the source.
                    </div>
                }
            />
            <DataWarehouseInitialBillingLimitNotice />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.dataWarehouseSettings(tab as DataWarehouseSettingsTab))}
                tabs={Object.entries(tabToContent).map(([tab, content]) => ({
                    label: (
                        <span className="flex justify-center items-center justify-between gap-1">
                            {humanFriendlyDataWarehouseSettingsTabName(tab as DataWarehouseSettingsTab)}{' '}
                        </span>
                    ),
                    key: tab,
                    content: content,
                }))}
            />
        </div>
    )
}
