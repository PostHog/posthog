import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SuggestedModelsPreview } from 'products/warehouse_suggestions/frontend/components/SuggestedModelsPreview'

import { ModelsList } from './ModelsList'
import { modelsListLogic } from './modelsListLogic'
import { ModelsOverviewEmptyState } from './ModelsOverviewEmptyState'
import { ModelsOverviewIssues } from './ModelsOverviewIssues'
import { modelsOverviewLogic } from './modelsOverviewLogic'
import { modelsSceneLogic } from './modelsSceneLogic'

function ModelsListTab(): JSX.Element {
    const { showFirstView } = useValues(modelsListLogic)
    const { checksStatus } = useValues(modelsOverviewLogic)

    return (
        <div data-quill>
            {showFirstView ? (
                <ModelsOverviewEmptyState variant="first-view" checksStatus={checksStatus} />
            ) : (
                <ModelsList />
            )}
        </div>
    )
}

export function ModelsOverviewTab(): JSX.Element {
    const { catalogRestructureEnabled } = useValues(modelsSceneLogic)
    const { showFirstView, checksStatus } = useValues(modelsOverviewLogic)
    const { loadNodes, loadDataWarehouseSavedQueries } = useActions(modelsOverviewLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const attentionRef = useRef<HTMLDivElement>(null)

    if (catalogRestructureEnabled) {
        return <ModelsListTab />
    }

    if (showFirstView) {
        return (
            <div data-quill>
                <ModelsOverviewEmptyState variant="first-view" checksStatus={checksStatus} />
            </div>
        )
    }

    return (
        <div data-quill className="flex flex-col gap-6">
            <div ref={attentionRef} tabIndex={-1}>
                <ModelsOverviewIssues />
            </div>
            {featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS] && (
                <SuggestedModelsPreview
                    onAccepted={() => {
                        loadNodes()
                        loadDataWarehouseSavedQueries()
                    }}
                    emptyFocusRef={attentionRef}
                />
            )}
        </div>
    )
}
