import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SuggestedModelsPreview } from 'products/warehouse_suggestions/frontend/components/SuggestedModelsPreview'

import { ModelsOverviewEmptyState } from './ModelsOverviewEmptyState'
import { ModelsOverviewIssues } from './ModelsOverviewIssues'
import { modelsOverviewLogic } from './modelsOverviewLogic'
import { ModelsOverviewStats } from './ModelsOverviewStats'

export function ModelsOverviewTab(): JSX.Element {
    const { showFirstView, checksStatus } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries } = useActions(modelsOverviewLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const summaryRef = useRef<HTMLDivElement>(null)

    if (showFirstView) {
        return (
            <div data-quill>
                <ModelsOverviewEmptyState variant="first-view" checksStatus={checksStatus} />
            </div>
        )
    }

    return (
        <div data-quill className="flex flex-col gap-6">
            <div ref={summaryRef} tabIndex={-1} aria-label="Models summary">
                <ModelsOverviewStats />
            </div>
            <ModelsOverviewIssues />
            {featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS] && (
                <SuggestedModelsPreview
                    onAccepted={() => {
                        loadNodes()
                        loadDataWarehouseSavedQueries()
                    }}
                    emptyFocusRef={summaryRef}
                />
            )}
        </div>
    )
}
