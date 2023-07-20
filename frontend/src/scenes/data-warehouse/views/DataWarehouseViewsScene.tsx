import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'
import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { DataWarehouseViewsContainer } from './DataWarehouseViewsContainer'

export const scene: SceneExport = {
    component: DataWarehouseViewsScene,
    logic: dataWarehouseViewsLogic,
}

export function DataWarehouseViewsScene(): JSX.Element {
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
                        These are the database tables you can query under SQL insights with{' '}
                        <a href="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </a>
                        . Connect your own tables from S3 to query data from outside posthog.{' '}
                        <a href="https://posthog.com/docs/data/data-warehouse">Learn more</a>
                    </div>
                }
            />
            {/* {(shouldShowProductIntroduction || shouldShowEmptyState) && (
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
            {!shouldShowEmptyState && <DataWarehouseViewsContainer />} */}
            <DataWarehousePageTabs tab={DataWarehouseTab.Views} />
            <DataWarehouseViewsContainer />
        </div>
    )
}
