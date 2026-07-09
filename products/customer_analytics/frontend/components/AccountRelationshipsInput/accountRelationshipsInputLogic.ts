import { afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { projectLogic } from 'scenes/projectLogic'

import { accountRelationshipDefinitionsList } from 'products/customer_analytics/frontend/generated/api'
import type { AccountRelationshipDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountRelationshipsInputLogicType } from './accountRelationshipsInputLogicType'

export const accountRelationshipsInputLogic = kea<accountRelationshipsInputLogicType>([
    path([
        'products',
        'customer_analytics',
        'frontend',
        'components',
        'AccountRelationshipsInput',
        'accountRelationshipsInputLogic',
    ]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    loaders(({ values }) => ({
        definitions: [
            [] as AccountRelationshipDefinitionApi[],
            {
                loadDefinitions: async (): Promise<AccountRelationshipDefinitionApi[]> => {
                    const response = await accountRelationshipDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
    })),
    listeners({
        loadDefinitionsFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'accountRelationshipsInputLogic.load' })
        },
    }),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
