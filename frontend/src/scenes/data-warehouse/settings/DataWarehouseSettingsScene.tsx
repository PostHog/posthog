import { LemonButton, LemonTabs, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehouseTab } from '~/types'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import { DataWarehouseManagedSourcesTable } from './DataWarehouseManagedSourcesTable'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseSelfManagedSourcesTable } from './DataWarehouseSelfManagedSourcesTable'

export const scene: SceneExport = {
    component: DataWarehouseSettingsScene,
    logic: dataWarehouseSceneLogic,
}

const tabToContent: Partial<Record<DataWarehouseTab, JSX.Element>> = {
    [DataWarehouseTab.ManagedSources]: <DataWarehouseManagedSourcesTable />,
    [DataWarehouseTab.SelfManagedSources]: <DataWarehouseSelfManagedSourcesTable />,
}

export const humanFriendlyDataWarehouseTabName = (tab: DataWarehouseTab): string => {
    switch (tab) {
        case DataWarehouseTab.ManagedSources:
            return 'Managed sources'
        case DataWarehouseTab.SelfManagedSources:
            return 'Self-Managed sources'
    }
}

export function DataWarehouseSettingsScene(): JSX.Element {
    const { currentTab } = useValues(dataWarehouseSceneLogic)

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            type="primary"
                            data-attr="new-data-warehouse-easy-link"
                            key="new-data-warehouse-easy-link"
                            to={urls.dataWarehouseTable()}
                        >
                            Link source
                        </LemonButton>
                    </>
                }
                caption={
                    <div>
                        Explore all your data in PostHog with{' '}
                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </Link>
                        . Connect your own tables from S3 to query data from outside PostHog.{' '}
                        <Link to="https://posthog.com/docs/data/data-warehouse">Learn more</Link>
                    </div>
                }
            />
            <DataWarehouseInitialBillingLimitNotice />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.dataWarehouseSettings(tab as DataWarehouseTab))}
                tabs={Object.entries(tabToContent).map(([tab, content]) => ({
                    label: (
                        <span className="flex items-center justify-between gap-1">
                            {humanFriendlyDataWarehouseTabName(tab as DataWarehouseTab)}{' '}
                        </span>
                    ),
                    key: tab,
                    content: content,
                }))}
            />
        </div>
    )
}
