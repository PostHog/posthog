import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { DestinationsTable } from './destinations/Destinations'
import { TransformationsTable } from './Transformations'

export function Overview(): JSX.Element {
    return (
        <div>
            <Link to={urls.pipeline(PipelineTab.Transformations)}>
                <h2 className="mt-4">Transformations</h2>
            </Link>
            <p>
                Modify and enrich your incoming data. Only active transformations are shown here.{' '}
                <Link to={urls.pipeline(PipelineTab.Transformations)}>See all.</Link>
            </p>
            <TransformationsTable inOverview={true} />
            <Link to={urls.pipeline(PipelineTab.Destinations)}>
                <h2 className="mt-4">Destinations</h2>
            </Link>
            <p>
                Send your data to destinations in real time or with batch exports. Only active Destinations are shown
                here. <Link to={urls.pipeline(PipelineTab.Destinations)}>See all.</Link>
            </p>
            <DestinationsTable defaultFilters={{ onlyActive: true }} />
        </div>
    )
}
