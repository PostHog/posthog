import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ProductKey } from '~/types'

export function DataPipelinesSources({ action }: { action: JSX.Element }): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(dataWarehouseSettingsLogic)

    return (
        <div className="flex flex-col gap-4">
            {!dataWarehouseSourcesLoading && dataWarehouseSources?.results.length === 0 ? (
                <ProductIntroduction
                    productName="Data Warehouse Source"
                    productKey={ProductKey.DATA_WAREHOUSE}
                    thingName="data source"
                    description="Use data warehouse sources to import data from your external data into PostHog."
                    isEmpty={dataWarehouseSources.results.length === 0 && !dataWarehouseSourcesLoading}
                    docsURL="https://posthog.com/docs/data-warehouse"
                    actionElementOverride={action}
                />
            ) : null}

            <FlaggedFeature flag="cdp-hog-sources">
                <>
                    <SceneSection
                        title={
                            <span className="flex items-center gap-2">
                                Event sources
                                <LemonTag type="primary" size="small">
                                    Experimental
                                </LemonTag>
                            </span>
                        }
                        description="PostHog can expose a webhook that you can configure however you need to receive data from a 3rd party with no in-between service necessary"
                    >
                        <HogFunctionList logicKey="data-pipelines-hog-functions-source-webhook" type="source_webhook" />
                    </SceneSection>
                    <SceneDivider />
                </>
            </FlaggedFeature>

            <SceneSection
                title="Managed data warehouse sources"
                description="PostHog can connect to external sources and automatically import data from them into the PostHog data warehouse"
            >
                <DataWarehouseManagedSourcesTable />
            </SceneSection>
            <SceneDivider />
            <SceneSection
                title="Self-managed data warehouse sources"
                description="Connect to your own data sources, making them queryable in PostHog"
            >
                <DataWarehouseSelfManagedSourcesTable />
            </SceneSection>
        </div>
    )
}
