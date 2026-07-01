import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { projectLogic } from 'scenes/projectLogic'

import { customPropertyDefinitionsList } from 'products/customer_analytics/frontend/generated/api'
import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountPropertiesInputLogicType } from './accountPropertiesInputLogicType'

export const accountPropertiesInputLogic = kea<accountPropertiesInputLogicType>([
    path([
        'products',
        'customer_analytics',
        'frontend',
        'components',
        'AccountPropertiesInput',
        'accountPropertiesInputLogic',
    ]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    loaders(({ values }) => ({
        definitions: [
            [] as CustomPropertyDefinitionApi[],
            {
                loadDefinitions: async (): Promise<CustomPropertyDefinitionApi[]> => {
                    const response = await customPropertyDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
    })),
    selectors({
        nameById: [
            (s) => [s.definitions],
            (definitions): Record<string, string> => Object.fromEntries(definitions.map((d) => [d.id, d.name])),
        ],
    }),
    listeners({
        loadDefinitionsFailure: ({ error }) => {
            posthog.captureException(error, { scope: 'accountPropertiesInputLogic.load' })
        },
    }),
    afterMount(({ actions }) => {
        actions.loadDefinitions()
    }),
])
