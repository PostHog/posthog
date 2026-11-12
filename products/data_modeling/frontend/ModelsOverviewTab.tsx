import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { QuillSuggestedModelsStrip } from 'products/warehouse_suggestions/frontend/components/QuillSuggestedModelsStrip'
import { SuggestedModelsStrip } from 'products/warehouse_suggestions/frontend/components/SuggestedModelsStrip'

import { catalogRestructureEnabled } from './catalogRestructure'
import { ModelsOverviewFirstView, ModelsOverviewHealthy } from './ModelsOverviewEmptyState'
import { ModelsOverviewIssues } from './ModelsOverviewIssues'
import { modelsOverviewLogic } from './modelsOverviewLogic'

function OverviewSuggestions(): JSX.Element | null {
    const { loadNodes, loadDataWarehouseSavedQueries } = useActions(modelsOverviewLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return null
    }
    const Strip = catalogRestructureEnabled(featureFlags) ? QuillSuggestedModelsStrip : SuggestedModelsStrip
    return (
        <Strip
            placement="overview"
            onAccepted={() => {
                loadNodes()
                loadDataWarehouseSavedQueries()
            }}
        />
    )
}

export function ModelsOverviewTab(): JSX.Element {
    const { showFirstView, nothingToReport, checksHealth, refreshSummary } = useValues(modelsOverviewLogic)

    if (showFirstView) {
        return (
            <div data-quill className="flex flex-col gap-6">
                <OverviewSuggestions />
                <ModelsOverviewFirstView checksHealth={checksHealth} />
            </div>
        )
    }

    if (nothingToReport) {
        return (
            <div data-quill className="flex flex-col gap-6">
                <OverviewSuggestions />
                <ModelsOverviewHealthy checksHealth={checksHealth} refreshSummary={refreshSummary} />
            </div>
        )
    }

    return (
        <div data-quill className="flex flex-col gap-6">
            <OverviewSuggestions />
            <ModelsOverviewIssues />
        </div>
    )
}
