import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { DataWarehouseViewLink } from '~/types'

import type { dataWarehouseJoinsLogicType } from './dataWarehouseJoinsLogicType'

export const dataWarehouseJoinsLogic = kea<dataWarehouseJoinsLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'dataWarehouseJoinsLogic']),
    loaders({
        joins: [
            [] as DataWarehouseViewLink[],
            {
                loadJoins: async () => {
                    const joins = await api.dataWarehouseViewLinks.list()
                    return joins.results
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadJoins()
    }),
])
