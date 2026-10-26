import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { getUsage } from '../../api'
import type { KnowledgeUsage } from '../../api'
import type { businessKnowledgeUsageLogicType } from './businessKnowledgeUsageLogicType'

export const businessKnowledgeUsageLogic = kea<businessKnowledgeUsageLogicType>([
    path(['products', 'business_knowledge', 'frontend', 'components', 'UsageMeter', 'businessKnowledgeUsageLogic']),
    loaders({
        usage: [
            null as KnowledgeUsage | null,
            {
                loadUsage: async () => await getUsage(),
            },
        ],
    }),
    selectors({
        ingestionLimited: [(s) => [s.usage], (usage): boolean => !!usage?.chunks.limited],
        retrievalLimited: [(s) => [s.usage], (usage): boolean => !!usage?.queries.limited],
    }),
    afterMount(({ actions }) => {
        actions.loadUsage()
    }),
])
