import { kea, path, selectors } from 'kea'
import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

import type { ingestionWarningsLogicType } from './ingestionWarningsLogicType'

export const ingestionWarningsLogic = kea<ingestionWarningsLogicType>([
    path(['scenes', 'data-management', 'ingestion-warnings', 'ingestionWarningsLogic']),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        name: `Data Management`,
                        path: urls.eventDefinitions(),
                    },
                    {
                        name: 'Ingestion Warnings',
                        path: urls.ingestionWarnings(),
                    },
                ]
            },
        ],
    }),
])
