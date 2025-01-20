import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu, Link } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { urls } from 'scenes/urls'

import { PipelineStage, PipelineTab } from '~/types'

import { DESTINATION_TYPES } from './destinations/constants'
import { DestinationsTable } from './destinations/Destinations'
import { TransformationsTable } from './Transformations'

export function Overview(): JSX.Element {
    const menuItems = [
        { label: 'Source', to: urls.pipelineNodeNew(PipelineStage.Source) },
        { label: 'Transformation', to: urls.pipelineNodeNew(PipelineStage.Transformation) },
        { label: 'Destination', to: urls.pipelineNodeNew(PipelineStage.Destination) },
    ]

    return (
        <>
            <PageHeader
                buttons={
                    <div className="shrink-0 flex items-center m-2">
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
                    </div>
                }
            />
            <div className="space-y-4">
                <div>
                    <Link to={urls.pipeline(PipelineTab.Sources)}>
                        <h2>Managed sources</h2>
                    </Link>
                    <div className="space-y-2">
                        <DataWarehouseManagedSourcesTable />
                    </div>
                </div>
                <div>
                    <Link to={urls.pipeline(PipelineTab.Sources)}>
                        <h2>Self-managed sources</h2>
                    </Link>
                    <div className="space-y-2">
                        <DataWarehouseSelfManagedSourcesTable />
                    </div>
                </div>
                <div>
                    <Link to={urls.pipeline(PipelineTab.Transformations)}>
                        <h2>Transformations</h2>
                    </Link>
                    <p>
                        Modify and enrich your incoming data. Only active transformations are shown here.{' '}
                        <Link to={urls.pipeline(PipelineTab.Transformations)}>See all.</Link>
                    </p>
                    <TransformationsTable inOverview={true} />
                </div>
                <div>
                    <Link to={urls.pipeline(PipelineTab.Destinations)}>
                        <h2>Destinations</h2>
                    </Link>
                    <p>
                        Send your data to destinations in real time or with batch exports. Only active Destinations are
                        shown here. <Link to={urls.pipeline(PipelineTab.Destinations)}>See all.</Link>
                    </p>
                    <DestinationsTable types={DESTINATION_TYPES} hideFeedback={true} hideAddDestinationButton={false} />
                </div>
            </div>
        </>
    )
}
