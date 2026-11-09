import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SuggestedModelsStrip } from 'products/warehouse_suggestions/frontend/components/SuggestedModelsStrip'

import { ModelsOverviewFirstView } from './ModelsOverviewEmptyState'
import { ModelsOverviewIssues } from './ModelsOverviewIssues'
import { modelsOverviewLogic } from './modelsOverviewLogic'

export function ModelsOverviewTab(): JSX.Element {
    const { showFirstView, checksHealth } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries } = useActions(modelsOverviewLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (showFirstView) {
        return (
            <div data-quill>
                <ModelsOverviewFirstView checksHealth={checksHealth} />
            </div>
        )
    }

    return (
        <div data-quill className="flex flex-col gap-6">
            <ModelsOverviewIssues />
            {featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS] && (
                <SuggestedModelsStrip
                    placement="overview"
                    onAccepted={() => {
                        loadNodes()
                        loadDataWarehouseSavedQueries()
                    }}
                />
            )}
        </div>
    )
}
