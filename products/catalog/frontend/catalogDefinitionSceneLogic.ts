import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

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
        setColumnEdits: (columnId: string, edits: PatchedUpdateColumnInputApi) => ({ columnId, edits }),
        clearColumnEdits: (columnId: string) => ({ columnId }),
        clearAllColumnEdits: true,
        replaceColumn: (column: CatalogColumnDTOApi) => ({ column }),
        saveChanges: true,
        discardChanges: true,
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
                clearAllColumnEdits: () => ({}),
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
        isDirty: [
            (s) => [s.pendingEdits, s.pendingColumnEdits],
            (edits, columnEdits): boolean =>
                Object.keys(edits).length > 0 || Object.values(columnEdits).some((e) => Object.keys(e).length > 0),
        ],
        breadcrumbs: [
            (s) => [s.definition],
            (definition): Breadcrumb[] => [
                { key: 'catalog', name: 'Semantic layer', path: urls.catalog() },
                { key: 'definition', name: definition?.name ?? 'Definition' },
            ],
        ],
    }),

    listeners(({ values, props, actions }) => ({
        discardChanges: () => {
            actions.clearEdits()
            actions.clearAllColumnEdits()
        },
        saveChanges: async () => {
            if (!values.isDirty) {
                return
            }
            const projectId = String(values.currentProjectId)
            const errors: string[] = []

            // Definition-level edits first.
            if (Object.keys(values.pendingEdits).length > 0) {
                try {
                    const updated = await catalogNodesPartialUpdate(projectId, props.id, values.pendingEdits)
                    actions.loadDefinitionSuccess(updated)
                    actions.clearEdits()
                } catch (error) {
                    errors.push(`definition: ${(error as Error).message}`)
                }
            }

            // Then each dirty column. Save in parallel so a 20-column edit doesn't
            // sequentialise on round-trip latency.
            const columnEntries = Object.entries(values.pendingColumnEdits).filter(
                ([, edits]) => Object.keys(edits).length > 0
            )
            const columnResults = await Promise.allSettled(
                columnEntries.map(async ([columnId, edits]) => {
                    const updated = await catalogColumnsPartialUpdate(projectId, columnId, edits)
                    actions.replaceColumn(updated)
                    actions.clearColumnEdits(columnId)
                })
            )
            columnResults.forEach((r, i) => {
                if (r.status === 'rejected') {
                    errors.push(`column ${columnEntries[i][0]}: ${(r.reason as Error).message}`)
                }
            })

            if (errors.length === 0) {
                lemonToast.success('Saved')
            } else {
                lemonToast.error(`Failed to save: ${errors.join('; ')}`)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadDefinition()
    }),
])
