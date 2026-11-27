import { useValues } from 'kea'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAttributionLogic } from '../../logic/marketingAttributionLogic'
import { AttributionTable } from './AttributionTable'
import { ConversionPaths } from './ConversionPaths'

export function AttributionResults(): JSX.Element {
    const { query, pathsQuery } = useValues(marketingAttributionLogic)

    return (
        <div className="mt-4 flex flex-col gap-4 pb-8">
            {query && <AttributionTable query={query} attachTo={marketingAnalyticsLogic} />}
            {pathsQuery && <ConversionPaths query={pathsQuery} attachTo={marketingAnalyticsLogic} />}
        </div>
    )
}
