import { useValues } from 'kea'

import { modelsSceneLogic } from 'products/data_modeling/frontend/modelsSceneLogic'
import { ModelsUsageTab } from 'products/data_modeling/frontend/ModelsUsageTab'
import { QuillModelsUsageDateFilter } from 'products/data_modeling/frontend/QuillModelsUsageDateFilter'

export function CatalogUsageSection(): JSX.Element {
    const { savedQueryIdToNodeId } = useValues(modelsSceneLogic)
    return <ModelsUsageTab savedQueryIdToNodeId={savedQueryIdToNodeId} dateFilter={<QuillModelsUsageDateFilter />} />
}
