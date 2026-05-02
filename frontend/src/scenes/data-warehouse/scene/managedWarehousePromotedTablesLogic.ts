import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { AvailableManagedWarehouseSourceTable, ManagedWarehousePromotedTable } from '~/types'

import type { managedWarehousePromotedTablesLogicType } from './managedWarehousePromotedTablesLogicType'

interface PaginatedListResponse<T> {
    results: T[]
    next: string | null
    previous: string | null
    count: number
}

const endpoint = (teamId: number): string => `api/environments/${teamId}/managed_warehouse_promoted_tables`

export interface PromoteTableForm {
    source_schema_name: string
    source_table_name: string
}

export const managedWarehousePromotedTablesLogic = kea<managedWarehousePromotedTablesLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'managedWarehousePromotedTablesLogic']),

    actions({
        promoteTable: (form: PromoteTableForm) => form,
        deletePromotion: (id: string) => ({ id }),
        setIsCreating: (isCreating: boolean) => ({ isCreating }),
    }),

    loaders(() => ({
        promotedTables: [
            [] as ManagedWarehousePromotedTable[],
            {
                loadPromotedTables: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (teamId === null) {
                        return []
                    }
                    const result: PaginatedListResponse<ManagedWarehousePromotedTable> = await api.get(
                        endpoint(teamId)
                    )
                    return result.results
                },
            },
        ],
        availableSourceTables: [
            [] as AvailableManagedWarehouseSourceTable[],
            {
                loadAvailableSourceTables: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (teamId === null) {
                        return []
                    }
                    return await api.get<AvailableManagedWarehouseSourceTable[]>(
                        `${endpoint(teamId)}/available_source_tables`
                    )
                },
            },
        ],
    })),

    reducers({
        isCreating: [
            false,
            {
                setIsCreating: (_, { isCreating }) => isCreating,
                promoteTableSuccess: () => false,
            },
        ],
        isSaving: [
            false,
            {
                promoteTable: () => true,
                promoteTableSuccess: () => false,
                promoteTableFailure: () => false,
            },
        ],
    }),

    listeners(({ actions }) => ({
        promoteTable: async (form) => {
            const teamId = teamLogic.values.currentTeamId
            if (teamId === null) {
                actions.promoteTableFailure()
                return
            }
            try {
                await api.create(endpoint(teamId), form)
                lemonToast.success('Table promoted')
                actions.loadPromotedTables()
                actions.loadAvailableSourceTables()
                actions.promoteTableSuccess()
            } catch (e: any) {
                lemonToast.error(`Failed to promote table: ${e.detail || e.message || 'Unknown error'}`)
                actions.promoteTableFailure()
            }
        },

        deletePromotion: async ({ id }) => {
            const teamId = teamLogic.values.currentTeamId
            if (teamId === null) {
                return
            }
            try {
                await api.delete(`${endpoint(teamId)}/${id}`)
                lemonToast.success('Promotion removed')
                actions.loadPromotedTables()
                actions.loadAvailableSourceTables()
            } catch (e: any) {
                lemonToast.error(`Failed to remove promotion: ${e.detail || e.message || 'Unknown error'}`)
            }
        },

        setIsCreating: ({ isCreating }) => {
            if (isCreating) {
                actions.loadAvailableSourceTables()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadPromotedTables()
    }),
])
