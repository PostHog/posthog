import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { QuillSuggestedModelsStrip } from 'products/warehouse_suggestions/frontend/components/QuillSuggestedModelsStrip'
import { SuggestedModelsStrip } from 'products/warehouse_suggestions/frontend/components/SuggestedModelsStrip'

import { catalogRestructureEnabled } from './catalogRestructure'
import { modelsOverviewLogic } from './modelsOverviewLogic'
import { ModelsOverviewStatus } from './ModelsOverviewStatus'

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
    return (
        <div data-quill className="flex flex-col gap-6">
            <OverviewSuggestions />
            <ModelsOverviewStatus />
        </div>
    )
}
