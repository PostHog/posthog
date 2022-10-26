import { kea, selectors, path } from 'kea'
import { Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'

import type { actionsLogicType } from './actionsLogicType'

export const actionsLogic = kea<actionsLogicType>([
    path(['scenes', 'actions', 'actionsLogic']),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    name: `Data Management`,
                    path: urls.eventDefinitions(),
                },
                {
                    name: 'Actions',
                    path: urls.actions(),
                },
            ],
        ],
    }),
])
