import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { urls } from 'scenes/urls'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { nonHogFunctionsLogic } from './utils/nonHogFunctionsLogic'

export function DataPipelinesOverview(): JSX.Element {
    const { hogFunctionPluginsDestinations, hogFunctionBatchExports } = useValues(nonHogFunctionsLogic)
    const { loadHogFunctionPluginsDestinations, loadHogFunctionBatchExports } = useActions(nonHogFunctionsLogic)

    useOnMountEffect(() => {
        loadHogFunctionPluginsDestinations()
        loadHogFunctionBatchExports()
    })

    return (
        <>
            <div className="flex flex-col gap-4">
                <FlaggedFeature flag="cdp-hog-sources">
                    <>
                        <SceneSection
                            title="Event sources"
                            actions={<Link to={urls.dataPipelines('sources')}>See all</Link>}
                        >
                            <HogFunctionList logicKey="overview-data-sources" type="source_webhook" />
                        </SceneSection>
                        <SceneDivider />
                    </>
                </FlaggedFeature>
                <SceneSection
                    title="Managed data warehouse sources"
                    actions={<Link to={urls.dataPipelines('sources')}>See all</Link>}
                >
                    <DataWarehouseManagedSourcesTable />
                </SceneSection>
                <SceneDivider />
                <SceneSection
                    title="Self-managed data warehouse sources"
                    actions={<Link to={urls.dataPipelines('sources')}>See all</Link>}
                >
                    <DataWarehouseSelfManagedSourcesTable />
                </SceneSection>
                <SceneDivider />
                <SceneSection
                    title="Transformations"
                    description="Modify and enrich your incoming data. Only active transformations are shown here."
                    actions={<Link to={urls.dataPipelines('transformations')}>See all</Link>}
                >
                    <HogFunctionList logicKey="transformation" type="transformation" hideFeedback={true} />
                </SceneSection>
                <SceneDivider />

                <SceneSection
                    title="Destinations"
                    description="Send your data to destinations in real time or with batch exports. Only active Destinations are shown here."
                    actions={<Link to={urls.dataPipelines('destinations')}>See all</Link>}
                >
                    <HogFunctionList
                        logicKey="destination"
                        type="destination"
                        hideFeedback={true}
                        manualFunctions={[
                            ...(hogFunctionPluginsDestinations ?? []),
                            ...(hogFunctionBatchExports ?? []),
                        ]}
                    />
                </SceneSection>
            </div>
        </>
    )
}
