import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

export function DataPipelinesSources({ newUrl }: { newUrl?: string }): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    const newButton = (
        <LemonButton
            to={newUrl ?? urls.dataPipelinesNew('source')}
            type="primary"
            icon={<IconPlusSmall />}
            size="small"
        >
            New source
        </LemonButton>
    )

    return (
        <>
            <PageHeader buttons={newButton} />
            <div className="space-y-4">
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

                <FlaggedFeature flag="cdp-hog-sources">
                    <div>
                        <h2>Event sources</h2>
                        <p>
                            PostHog can expose a webhook that you can configure however you need to receive data from a
                            3rd party with no in-between service necessary
                        </p>
                        <HogFunctionList logicKey="data-pipelines-hog-functions-source-webhook" type="source_webhook" />
                    </div>
                </FlaggedFeature>

                <div>
                    <h2>Managed data warehouse sources</h2>
                    <p>
                        PostHog can connect to external sources and automatically import data from them into the PostHog
                        data warehouse
                    </p>
                    <DataWarehouseManagedSourcesTable />
                </div>
                <div>
                    <h2>Self-managed data warehouse sources</h2>
                    <p>Connect to your own data sources, making them queryable in PostHog</p>
                    <DataWarehouseSelfManagedSourcesTable />
                </div>
            </div>
        </>
    )
}
