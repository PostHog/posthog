import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
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
    actions({
        addPendingDefinition: (definitionId: string) => ({ definitionId }),
        removePendingDefinition: (definitionId: string) => ({ definitionId }),
    }),
    reducers({
        // Rows the user added but hasn't assigned yet. They stay out of the input value because
        // a null assignment ends the account's active assignment when the workflow runs.
        pendingDefinitionIds: [
            [] as string[],
            {
                addPendingDefinition: (state, { definitionId }) => [...state, definitionId],
                removePendingDefinition: (state, { definitionId }) => state.filter((id) => id !== definitionId),
            },
        ],
    }),
    loaders(({ values }) => ({
        definitions: [
            [] as AccountRelationshipDefinitionApi[],
            {
                loadDefinitions: async (): Promise<AccountRelationshipDefinitionApi[]> => {
                    const results: AccountRelationshipDefinitionApi[] = []
                    let offset = 0
                    let response
                    do {
                        response = await accountRelationshipDefinitionsList(String(values.currentProjectId), {
                            limit: 100,
                            offset,
                        })
                        results.push(...response.results)
                        offset += response.results.length
                    } while (response.next && response.results.length > 0)
                    return results
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
