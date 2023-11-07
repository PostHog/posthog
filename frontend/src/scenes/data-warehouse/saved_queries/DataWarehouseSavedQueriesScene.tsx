import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'
import { dataWarehouseSavedQueriesLogic } from './dataWarehouseSavedQueriesLogic'
import { DataWarehouseSavedQueriesContainer } from './DataWarehouseSavedQueriesContainer'
import { useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { router } from 'kea-router'
import { ProductKey } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Error404 } from '~/layout/Error404'

export const scene: SceneExport = {
    component: DataWarehouseSavedQueriesScene,
    logic: dataWarehouseSavedQueriesLogic,
}

export function DataWarehouseSavedQueriesScene(): JSX.Element {
    const { shouldShowEmptyState, shouldShowProductIntroduction } = useValues(dataWarehouseSavedQueriesLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_VIEWS]) {
        return <Error404 />
    }

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
                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </Link>
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
                    productKey={ProductKey.DATA_WAREHOUSE_SAVED_QUERY}
                />
            )}
            {!shouldShowEmptyState && <DataWarehouseSavedQueriesContainer />}
        </div>
    )
}
