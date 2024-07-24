import { LemonButton, LemonTabs, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehouseTab } from '~/types'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import { DataWarehouseManagedSourcesTable } from '../settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from '../settings/DataWarehouseSelfManagedSourcesTable'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseTables } from './DataWarehouseTables'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

const tabToContent: Partial<Record<DataWarehouseTab, JSX.Element>> = {
    [DataWarehouseTab.Explore]: <Explore />,
    [DataWarehouseTab.ManagedSources]: <DataWarehouseManagedSourcesTable />,
    [DataWarehouseTab.SelfManagedSources]: <DataWarehouseSelfManagedSourcesTable />,
}

export const humanFriendlyDataWarehouseTabName = (tab: DataWarehouseTab): string => {
    switch (tab) {
        case DataWarehouseTab.Explore:
            return 'Explore'
        case DataWarehouseTab.ManagedSources:
            return 'Managed sources'
        case DataWarehouseTab.SelfManagedSources:
            return 'Self-Managed sources'
    }
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { currentTab } = useValues(dataWarehouseSceneLogic)

    const { insightProps, insightSaving } = useValues(
        insightLogic({
            dashboardItemId: 'new',
            cachedInsight: null,
        })
    )

    const { saveAs } = useActions(insightDataLogic(insightProps))

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        {currentTab === DataWarehouseTab.Explore && (
                            <LemonButton
                                type="primary"
                                data-attr="save-exploration"
                                onClick={() => saveAs(true)}
                                loading={insightSaving}
                            >
                                Save as insight
                            </LemonButton>
                        )}

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
                onChange={(tab) => router.actions.push(urls.dataWarehouse(tab as DataWarehouseTab))}
                tabs={Object.entries(tabToContent).map(([tab, content]) => ({
                    label: (
                        <span className="flex justify-center items-center justify-between gap-1">
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

function Explore(): JSX.Element {
    return (
        <BindLogic logic={insightSceneLogic} props={{}}>
            <DataWarehouseTables />
        </BindLogic>
    )
}
