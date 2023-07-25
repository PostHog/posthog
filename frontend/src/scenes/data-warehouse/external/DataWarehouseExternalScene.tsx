import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ProductKey } from '~/types'
import { DataWarehouseTablesContainer } from './DataWarehouseTables'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { shouldShowEmptyState, shouldShowProductIntroduction } = useValues(dataWarehouseSceneLogic)

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Data Warehouse
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                buttons={
                    <LemonButton
                        type="primary"
                        to={urls.dataWarehouseTable('new')}
                        data-attr="new-data-warehouse-table"
                    >
                        New Table
                    </LemonButton>
                }
                caption={
                    <div>
                        These are external data sources you can query under SQL insights with{' '}
                        <a href="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </a>
                        . Connect your own tables from S3 to query data from outside posthog.{' '}
                        <a href="https://posthog.com/docs/data/data-warehouse">Learn more</a>
                    </div>
                }
            />
            <DataWarehousePageTabs tab={DataWarehouseTab.External} />
            {(shouldShowProductIntroduction || shouldShowEmptyState) && (
                <ProductIntroduction
                    productName={'Data Warehouse'}
                    thingName={'data warehouse table'}
                    description={
                        'Bring your production database, revenue data, CRM contacts or any other data into PostHog.'
                    }
                    action={() => router.actions.push(urls.dataWarehouseTable('new'))}
                    isEmpty={shouldShowEmptyState}
                    docsURL="https://posthog.com/docs/data/data-warehouse"
                    productKey={ProductKey.DATA_WAREHOUSE}
                />
            )}
            {!shouldShowEmptyState && <DataWarehouseTablesContainer />}
        </div>
    )
}
