import { kea, path, selectors } from 'kea'
import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

import type { ingestionWarningsLogicType } from './ingestionWarningsLogicType'

export interface IngestionWarningSummary {
    type: string
    lastSeen: string
    warnings: IngestionWarning[]
}

export interface IngestionWarning {
    type: string
    timestamp: string
    details: Record<string, any>
}

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
        data: [
            () => [],
            () => [
                {
                    type: 'cannot_merge_already_identified',
                    lastSeen: '2022-09-27T07:49:51.713000+00:00',
                    warnings: [
                        {
                            type: 'cannot_merge_already_identified',
                            timestamp: '2022-09-27T07:49:51.713000+00:00',
                            details: {
                                sourcePerson: 'some-uuid',
                                sourcePersonDistinctId: 'some-distinct-id',
                                targetPerson: 'another-uuid',
                                targetPersonDistinctId: 'another-distinct-id',
                            },
                        },
                        {
                            type: 'cannot_merge_already_identified',
                            timestamp: '2022-08-27T07:49:51.713000+00:00',
                            details: {
                                sourcePerson: 'x-uuid',
                                sourcePersonDistinctId: 'Alice',
                                targetPerson: 'y-uuid',
                                targetPersonDistinctId: 'Bob',
                            },
                        },
                    ],
                } as IngestionWarningSummary,
            ],
        ],
    }),
])
