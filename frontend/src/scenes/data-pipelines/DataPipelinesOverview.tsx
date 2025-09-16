import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { PageHeader } from 'lib/components/PageHeader'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { urls } from 'scenes/urls'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { nonHogFunctionsLogic } from './utils/nonHogFunctionsLogic'

export function DataPipelinesOverview(): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    const menuItems: LemonMenuItems = [
        {
            label: 'Source',
            to: urls.dataPipelinesNew('source'),
            'data-attr': 'data-warehouse-data-pipelines-overview-new-source',
        },
        { label: 'Transformation', to: urls.dataPipelinesNew('transformation') },
        { label: 'Destination', to: urls.dataPipelinesNew('destination') },
    ]

    const { hogFunctionPluginsDestinations, hogFunctionBatchExports } = useValues(nonHogFunctionsLogic)
    const { loadHogFunctionPluginsDestinations, loadHogFunctionBatchExports } = useActions(nonHogFunctionsLogic)

    useOnMountEffect(() => {
        loadHogFunctionPluginsDestinations()
        loadHogFunctionBatchExports()
    })

    return (
        <>
            <PageHeader
                buttons={
                    <LemonMenu items={menuItems}>
                        <LemonButton
                            data-attr="new-pipeline-button"
                            icon={<IconPlusSmall />}
                            size="small"
                            type="primary"
                        >
                            New
                        </LemonButton>
                    </LemonMenu>
                }
            />
            <div className="flex flex-col gap-4">
                <FlaggedFeature flag="cdp-hog-sources">
                    <>
                        <SceneSection
                            title="Event sources"
                            actions={<Link to={urls.dataPipelines('sources')}>See all</Link>}
                            hideTitleAndDescription={!newSceneLayout}
                        >
                            {!newSceneLayout && (
                                <Link to={urls.dataPipelines('sources')}>
                                    <h2>Event sources</h2>
                                </Link>
                            )}
                            <HogFunctionList logicKey="overview-data-sources" type="source_webhook" />
                        </SceneSection>
                        <SceneDivider />
                    </>
                </FlaggedFeature>
                <SceneSection
                    title="Managed data warehouse sources"
                    actions={<Link to={urls.dataPipelines('sources')}>See all</Link>}
                    hideTitleAndDescription={!newSceneLayout}
                >
                    {!newSceneLayout && (
                        <Link to={urls.dataPipelines('sources')}>
                            <h2>Managed datw warehouse sources</h2>
                        </Link>
                    )}
                    <DataWarehouseManagedSourcesTable />
                </SceneSection>
                <SceneDivider />
                <SceneSection
                    title="Self-managed data warehouse sources"
                    actions={<Link to={urls.dataPipelines('sources')}>See all</Link>}
                    hideTitleAndDescription={!newSceneLayout}
                >
                    {!newSceneLayout && (
                        <Link to={urls.dataPipelines('sources')}>
                            <h2>Self-managed data warehouse sources</h2>
                        </Link>
                    )}
                    <DataWarehouseSelfManagedSourcesTable />
                </SceneSection>
                <SceneDivider />
                <SceneSection
                    title="Transformations"
                    description="Modify and enrich your incoming data. Only active transformations are shown here."
                    actions={<Link to={urls.dataPipelines('transformations')}>See all</Link>}
                    hideTitleAndDescription={!newSceneLayout}
                >
                    {!newSceneLayout && (
                        <>
                            <Link to={urls.dataPipelines('transformations')}>
                                <h2>Transformations</h2>
                            </Link>
                            <p>
                                Modify and enrich your incoming data. Only active transformations are shown here.{' '}
                                <Link to={urls.dataPipelines('transformations')}>See all.</Link>
                            </p>
                        </>
                    )}
                    <HogFunctionList logicKey="transformation" type="transformation" hideFeedback={true} />
                </SceneSection>
                <SceneDivider />

                <SceneSection
                    title="Destinations"
                    description="Send your data to destinations in real time or with batch exports. Only active Destinations are shown here."
                    actions={<Link to={urls.dataPipelines('destinations')}>See all</Link>}
                    hideTitleAndDescription={!newSceneLayout}
                >
                    {!newSceneLayout && (
                        <>
                            <Link to={urls.dataPipelines('destinations')}>
                                <h2>Destinations</h2>
                            </Link>
                            <p>
                                Send your data to destinations in real time or with batch exports. Only active
                                Destinations are shown here.{' '}
                                <Link to={urls.dataPipelines('destinations')}>See all.</Link>
                            </p>
                        </>
                    )}
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
