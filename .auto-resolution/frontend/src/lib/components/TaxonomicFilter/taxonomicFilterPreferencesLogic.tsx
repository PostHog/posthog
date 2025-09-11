import { actions, kea, path, reducers } from 'kea'

import type { taxonomicFilterPreferencesLogicType } from './taxonomicFilterPreferencesLogicType'

export type TaxonomicFilterEventOrderingOptions = 'name' | '-last_seen_at' | null

export const taxonomicFilterPreferencesLogic = kea<taxonomicFilterPreferencesLogicType>([
    path(['lib', 'components', 'TaxonomicFilter', 'taxonomicFilterPreferencesLogic']),
    actions(() => ({
        setEventOrdering: (order: TaxonomicFilterEventOrderingOptions) => ({ order }),
    })),
    reducers(() => ({
        eventOrdering: [
            null as TaxonomicFilterEventOrderingOptions,
            { persist: true },
            {
                setEventOrdering: (_state, { order }) => order,
            },
        ],
    })),
])
