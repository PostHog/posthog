import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

export function DataPipelinesSources(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    const newButton = (
        <LemonButton to={urls.dataPipelinesNew('source')} type="primary" icon={<IconPlusSmall />} size="small">
            New source
        </LemonButton>
    )

    return (
        <>
            <PageHeader buttons={newButton} />
            <div className="deprecated-space-y-4">
                {!dataWarehouseSourcesLoading && dataWarehouseSources?.results.length === 0 ? (
                    <ProductIntroduction
                        productName="Data Warehouse Source"
                        productKey={ProductKey.DATA_WAREHOUSE}
                        thingName="data source"
                        description="Use data warehouse sources to import data from your external data into PostHog."
                        isEmpty={dataWarehouseSources.results.length === 0 && !dataWarehouseSourcesLoading}
                        docsURL="https://posthog.com/docs/data-warehouse"
                        actionElementOverride={newButton}
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
                    <h2>Self-managed sources</h2>
                    <p>Connect to your own data sources, making them queryable in PostHog</p>
                    <DataWarehouseSelfManagedSourcesTable />
                </div>
            </div>
        </>
    )
}
