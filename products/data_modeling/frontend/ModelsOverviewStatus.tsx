import { useValues } from 'kea'

import { ModelsOverviewFirstView, ModelsOverviewHealthy } from './ModelsOverviewEmptyState'
import { ModelsOverviewIssues } from './ModelsOverviewIssues'
import { modelsOverviewLogic } from './modelsOverviewLogic'

export function ModelsOverviewStatus(): JSX.Element {
    const { showFirstView, nothingToReport, checksHealth, refreshSummary } = useValues(modelsOverviewLogic)

    if (showFirstView) {
        return <ModelsOverviewFirstView checksHealth={checksHealth} />
    }
    if (nothingToReport) {
        return <ModelsOverviewHealthy checksHealth={checksHealth} refreshSummary={refreshSummary} />
    }
    return <ModelsOverviewIssues />
}
