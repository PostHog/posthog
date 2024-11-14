import { IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { DestinationsTable } from './destinations/Destinations'
import { overlayForNewPipelineMenu } from './NewMenu'
import { TransformationsTable } from './Transformations'

export function Overview(): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            type="primary"
                            sideAction={{
                                dropdown: {
                                    placement: 'bottom-end',
                                    className: 'new-pipeline-overlay',
                                    actionable: true,
                                    overlay: overlayForNewPipelineMenu('some-data-attr-here'),
                                },
                                'data-attr': 'new-pipeline-dropdown',
                            }}
                            data-attr="new-pipeline-button"
                            size="small"
                            icon={<IconPlusSmall />}
                        >
                            New
                        </LemonButton>
                    </>
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
                    <DestinationsTable />
                </div>
            </div>
        </>
    )
}
