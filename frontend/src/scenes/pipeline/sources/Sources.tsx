import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'

import { PipelineStage, ProductKey } from '~/types'

import { NewButton } from '../NewButton'

export function Sources(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    return (
        <>
            <PageHeader buttons={<NewButton stage={PipelineStage.Source} />} />
            <div className="space-y-4">
                {!dataWarehouseSourcesLoading && dataWarehouseSources?.results.length === 0 ? (
                    <ProductIntroduction
                        productName="Data Warehouse Source"
                        productKey={ProductKey.DATA_WAREHOUSE}
                        thingName="data source"
                        description="Use data warehouse sources to import data from your external data into PostHog."
                        isEmpty={dataWarehouseSources.results.length === 0 && !dataWarehouseSourcesLoading}
                        docsURL="https://posthog.com/docs/data-warehouse"
                        actionElementOverride={<NewButton stage={PipelineStage.Source} />}
                    />
                ) : null}

                <div>
                    <h2>Managed sources</h2>
                    <p>
                        PostHog can connect to external sources and automatically import data from them into the PostHog
                        data warehouse
                    </p>
                    <DataWarehouseManagedSourcesTable />
                </div>
                <div>
                    <h2>Self managed sources</h2>
                    <p>Connect to your own data sources, making them queryable in PostHog</p>
                    <DataWarehouseSelfManagedSourcesTable />
                </div>
            </div>
        </>
    )
}
