import { Link } from '@posthog/lemon-ui'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { DestinationsTable } from './destinations/Destinations'
import { TransformationsTable } from './Transformations'

export function Overview(): JSX.Element {
    return (
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
                <DestinationsTable defaultFilters={{ onlyActive: true }} />
            </div>
        </div>
    )
}
