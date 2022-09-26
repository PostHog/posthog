import { kea } from 'kea'
import api from 'lib/api'
import { Breadcrumb, PersonType } from '~/types'
import { urls } from 'scenes/urls'

import type { usageWarningsTableLogicType } from './UsageWarningsTableLogicType'

export const usageWarningsTableLogic = kea<usageWarningsTableLogicType>({
    path: () => ['scenes', 'data-management', 'warnings', 'usageWarningsTableLogic'],
    actions: {
        loadPerson: (id: string) => ({ id }),
    },
    selectors: () => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        name: `Data Management`,
                        path: urls.eventDefinitions(),
                    },
                    {
                        name: 'Warnings',
                        path: urls.usageWarnings(),
                    },
                ]
            },
        ],
    }),
    loaders: () => ({
        // TODO: load the right person immediately
        person: [
            null as PersonType | null,
            {
                loadPerson: async ({ id }): Promise<PersonType | null> => {
                    const response = await api.persons.list({ distinct_id: id })
                    // TODO: if no results
                    const person = response.results[0]
                    return person
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPerson('$posthog_warnings')
        },
    }),
})
