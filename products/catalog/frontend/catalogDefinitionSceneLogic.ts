import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    catalogColumnsPartialUpdate,
    catalogNodesPartialUpdate,
    catalogNodesRetrieve,
} from 'products/catalog/frontend/generated/api'
import type {
    CatalogColumnDTOApi,
    CatalogNodeDTOApi,
    PatchedUpdateColumnInputApi,
    PatchedUpdateNodeInputApi,
} from 'products/catalog/frontend/generated/api.schemas'

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
        setColumnEdits: (columnId: string, edits: PatchedUpdateColumnInputApi) => ({ columnId, edits }),
        clearColumnEdits: (columnId: string) => ({ columnId }),
        saveColumn: (columnId: string) => ({ columnId }),
        replaceColumn: (column: CatalogColumnDTOApi) => ({ column }),
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
        pendingColumnEdits: [
            {} as Record<string, PatchedUpdateColumnInputApi>,
            {
                setColumnEdits: (state, { columnId, edits }) => ({
                    ...state,
                    [columnId]: { ...state[columnId], ...edits },
                }),
                clearColumnEdits: (state, { columnId }) => {
                    const next = { ...state }
                    delete next[columnId]
                    return next
                },
            },
        ],
        definition: {
            // Swap a column row in-place after a successful column save so the
            // table reflects the new values without a full refetch.
            replaceColumn: (state, { column }) => {
                if (!state) {
                    return state
                }
                return {
                    ...state,
                    columns: state.columns.map((c) => (c.id === column.id ? column : c)),
                }
            },
        },
    }),

    selectors({
        isDirty: [(s) => [s.pendingEdits], (edits): boolean => Object.keys(edits).length > 0],
        breadcrumbs: [
            (s) => [s.definition],
            (definition): Breadcrumb[] => [
                { key: 'catalog', name: 'Catalog', path: urls.catalog() },
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
        saveColumn: async ({ columnId }) => {
            const edits = values.pendingColumnEdits[columnId]
            if (!edits || Object.keys(edits).length === 0) {
                return
            }
            try {
                const updated = await catalogColumnsPartialUpdate(String(values.currentProjectId), columnId, edits)
                actions.replaceColumn(updated)
                actions.clearColumnEdits(columnId)
                lemonToast.success(`Column ${updated.name} saved`)
            } catch (error) {
                lemonToast.error(`Failed to save column: ${(error as Error).message}`)
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/catalog/definitions/:id': () => {
            actions.loadDefinition()
        },
    })),
])
