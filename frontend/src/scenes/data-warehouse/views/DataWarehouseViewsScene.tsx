import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'
import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'
import { DataWarehouseViewsContainer } from './DataWarehouseViewsContainer'
import { useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { router } from 'kea-router'
import { ProductKey } from '~/types'

export const scene: SceneExport = {
    component: DataWarehouseViewsScene,
    logic: dataWarehouseViewsLogic,
}

export function DataWarehouseViewsScene(): JSX.Element {
    const { shouldShowEmptyState, shouldShowProductIntroduction } = useValues(dataWarehouseViewsLogic)
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
                        to={urls.insightNewHogQL('SELECT event AS event FROM events LIMIT 100')}
                        data-attr="new-data-warehouse-table"
                    >
                        New View
                    </LemonButton>
                }
                caption={
                    <div>
                        These are the saved views you can query under SQL insights with{' '}
                        <a href="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </a>
                        . Views can be used as tables in other queries.
                    </div>
                }
            />
            <DataWarehousePageTabs tab={DataWarehouseTab.Views} />
            {(shouldShowEmptyState || shouldShowProductIntroduction) && (
                <ProductIntroduction
                    productName={'Data Warehouse Views'}
                    thingName={'data warehouse view'}
                    description={'Save your queries as views to use them as tables in other queries.'}
                    action={() => router.actions.push(urls.insightNewHogQL('SELECT * FROM events LIMIT 100'))}
                    isEmpty={shouldShowEmptyState}
                    docsURL="https://posthog.com/docs/data/data-warehouse"
                    productKey={ProductKey.DATA_WAREHOUSE_VIEWS}
                />
            )}
            {!shouldShowEmptyState && <DataWarehouseViewsContainer />}
        </div>
    )
}
