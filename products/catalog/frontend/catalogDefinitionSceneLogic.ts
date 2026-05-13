import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import { catalogNodesPartialUpdate, catalogNodesRetrieve } from 'products/catalog/frontend/generated/api'
import type { CatalogNodeDTOApi, PatchedUpdateNodeInputApi } from 'products/catalog/frontend/generated/api.schemas'

import type { catalogDefinitionSceneLogicType } from './catalogDefinitionSceneLogicType'

export interface CatalogDefinitionSceneLogicProps {
    id: string
}

export const catalogDefinitionSceneLogic = kea<catalogDefinitionSceneLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogDefinitionSceneLogic']),
    props({} as CatalogDefinitionSceneLogicProps),
    key((props) => props.id),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setEdits: (edits: PatchedUpdateNodeInputApi) => ({ edits }),
        clearEdits: true,
        saveDefinition: true,
    }),

    loaders(({ values, props }) => ({
        definition: [
            null as CatalogNodeDTOApi | null,
            {
                loadDefinition: async () => {
                    return await catalogNodesRetrieve(String(values.currentProjectId), props.id)
                },
            },
        ],
    })),

    reducers({
        pendingEdits: [
            {} as PatchedUpdateNodeInputApi,
            {
                setEdits: (state, { edits }) => ({ ...state, ...edits }),
                clearEdits: () => ({}),
            },
        ],
    }),

    selectors({
        isDirty: [(s) => [s.pendingEdits], (edits): boolean => Object.keys(edits).length > 0],
        breadcrumbs: [
            (s) => [s.definition],
            (definition): Breadcrumb[] => [
                { key: 'catalog', name: 'Catalog' },
                { key: 'definition', name: definition?.name ?? 'Definition' },
            ],
        ],
    }),

    listeners(({ values, props, actions }) => ({
        saveDefinition: async () => {
            if (!values.isDirty) {
                return
            }
            try {
                const updated = await catalogNodesPartialUpdate(
                    String(values.currentProjectId),
                    props.id,
                    values.pendingEdits
                )
                actions.loadDefinitionSuccess(updated)
                actions.clearEdits()
                lemonToast.success('Definition saved')
            } catch (error) {
                lemonToast.error(`Failed to save definition: ${(error as Error).message}`)
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/catalog/definitions/:id': () => {
            actions.loadDefinition()
        },
    })),
])
