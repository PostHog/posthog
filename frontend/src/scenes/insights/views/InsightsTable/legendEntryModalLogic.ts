import { actions, kea, path, reducers, selectors } from 'kea'
import { DataColorToken } from 'lib/colors'

import { GraphDataset } from '~/types'

import type { legendEntryModalLogicType } from './legendEntryModalLogicType'

export const legendEntryModalLogic = kea<legendEntryModalLogicType>([
    path(['scenes', 'insights', 'views', 'InsightsTable', 'legendEntryModalLogic']),

    actions({
        openModal: (dataset: GraphDataset) => ({ dataset }),
        closeModal: true,
        setColor: (token: DataColorToken) => ({ token })
        save: true,
    }),

    reducers({
        dataset: [
            null as GraphDataset | null,
            {
                openModal: (_, { dataset }) => dataset,
                closeModal: () => null,
            },
        ],
        localColor: [
            null as DataColorToken | null,
            {
                setColor: (_, {token} => token)
            }
        ]
    }),

    selectors({
        modalVisible: [(s) => [s.dataset], (dataset): boolean => dataset !== null],
    }),
])
