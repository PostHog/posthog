import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { pipelineOverviewLogic } from './overviewLogic'

export function Overview(): JSX.Element {
    const { transformations, destinations, loading } = useValues(pipelineOverviewLogic)

    return (
        <div>
            {loading && <Spinner />}
            <h2>Filters</h2>
            <p>
                <i>None</i>
            </p>

            <h2>Transformations</h2>
            {transformations && <pre>{JSON.stringify(transformations, null, 2)}</pre>}

            <h2>Destinations</h2>
            {destinations && <pre>{JSON.stringify(destinations, null, 2)}</pre>}
        </div>
    )
}
