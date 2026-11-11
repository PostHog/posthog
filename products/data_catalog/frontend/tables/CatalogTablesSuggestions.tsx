import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { modelsOverviewLogic } from 'products/data_modeling/frontend/modelsOverviewLogic'
import { SuggestedCertificationsTable } from 'products/warehouse_suggestions/frontend/components/SuggestedCertificationsTable'
import { SuggestedModelsStrip } from 'products/warehouse_suggestions/frontend/components/SuggestedModelsStrip'

import { certificationsLogic } from '../certificationsLogic'

export function CatalogTablesSuggestions(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { loadNodes, loadDataWarehouseSavedQueries } = useActions(modelsOverviewLogic)
    const { loadCertifications } = useActions(certificationsLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return null
    }
    return (
        <>
            <SuggestedModelsStrip
                placement="tables_tab"
                onAccepted={() => {
                    loadNodes()
                    loadDataWarehouseSavedQueries()
                }}
            />
            <SuggestedCertificationsTable onAccepted={() => loadCertifications()} />
        </>
    )
}
