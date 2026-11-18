import { useActions, useValues } from 'kea'

import { dataCatalogMetricSceneLogic } from './dataCatalogMetricSceneLogic'
import { DataCatalogMetricApi } from './generated/api.schemas'
import { MetricLineagePanel } from './MetricLineagePanel'

export function MetricLineageTab({ metric }: { metric: DataCatalogMetricApi }): JSX.Element {
    const { lineage, lineageLoading, lineageProblem } = useValues(dataCatalogMetricSceneLogic)
    const { loadLineage, setActiveTab } = useActions(dataCatalogMetricSceneLogic)

    return (
        <MetricLineagePanel
            metric={metric}
            lineage={lineage}
            lineageLoading={lineageLoading}
            lineageProblem={lineageProblem}
            onRetry={loadLineage}
            onEditDefinition={() => setActiveTab('definition')}
        />
    )
}
