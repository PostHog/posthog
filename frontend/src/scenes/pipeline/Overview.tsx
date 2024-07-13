import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { DestinationsTable } from './Destinations'
import { TransformationsTable } from './Transformations'

export function Overview(): JSX.Element {
    return (
        <div>
            <h2 className="mt-4">Transformations</h2>
            <p>
                Showing only enabled, go to{' '}
                <Link to={urls.pipeline(PipelineTab.Transformations)}>Transformations tab</Link> to see all.
            </p>
            <TransformationsTable inOverview={true} />
            <h2 className="mt-4">Destinations</h2>
            <p>
                Showing only active, go to <Link to={urls.pipeline(PipelineTab.Destinations)}>Destinations tab</Link> to
                see all.
            </p>
            <DestinationsTable inOverview={true} />
        </div>
    )
}
