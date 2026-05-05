import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { materializedColumnsLogicType } from './materializedColumnsLogicType'

export enum MaterializedColumnSlotState {
    PENDING = 'PENDING',
    BACKFILL = 'BACKFILL',
    READY = 'READY',
    ERROR = 'ERROR',
}

export interface PropertyDefinition {
    id: number
    name: string
    property_type: string
    type: number
}

export interface MaterializedColumnSlot {
    id: string
    team: number
    property_definition: number
    property_definition_details: PropertyDefinition
    /** Null while in PENDING — a column is only assigned once the weekly workflow runs. */
    slot_index: number | null
    /** Set during compaction — ingestion dual-writes to both columns until the workflow swaps. */
    compaction_target_slot_index: number | null
    state: MaterializedColumnSlotState
    backfill_temporal_run_id: string | null
    error_message: string | null
    created_at: string
    updated_at: string
}

export interface SlotUsageSummary {
    team_id: number
    team_name: string
    /** Team-wide cap on materialized columns (matches MAX_SLOTS_PER_TEAM in the backend). */
    max_slots_per_team: number
    used_total: number
    available: number
}

export interface AutoMaterializedColumn {
    column_name: string
    property_name: string
    table_column: string
    is_disabled: boolean
    is_nullable: boolean
}

export const materializedColumnsLogic = kea<materializedColumnsLogicType>([
    path(['scenes', 'data-management', 'MaterializedColumns', 'materializedColumnsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        setShowCreateModal: (show: boolean) => ({ show }),
        deleteSlot: (slotId: string) => ({ slotId }),
        retrySlot: (slotId: string) => ({ slotId }),
    }),
    loaders(({ values }) => ({
        slots: [
            [] as MaterializedColumnSlot[],
            {
                loadSlots: async () => {
                    if (!values.currentTeam) {
                        return []
                    }
                    const response = await api.get(
                        `api/environments/${values.currentTeam.id}/materialized_column_slots/`
                    )
                    return response.results || []
                },
            },
        ],
        slotUsage: [
            null as SlotUsageSummary | null,
            {
                loadSlotUsage: async () => {
                    if (!values.currentTeam) {
                        return null
                    }
                    return await api.get(
                        `api/environments/${values.currentTeam.id}/materialized_column_slots/slot_usage/`
                    )
                },
            },
        ],
        availableProperties: [
            [] as PropertyDefinition[],
            {
                loadAvailableProperties: async () => {
                    if (!values.currentTeam) {
                        return []
                    }
                    return await api.get(
                        `api/environments/${values.currentTeam.id}/materialized_column_slots/available_properties/`
                    )
                },
            },
        ],
        autoMaterializedColumns: [
            [] as AutoMaterializedColumn[],
            {
                loadAutoMaterializedColumns: async () => {
                    if (!values.currentTeam) {
                        return []
                    }
                    return await api.get(
                        `api/environments/${values.currentTeam.id}/materialized_column_slots/auto_materialized/`
                    )
                },
            },
        ],
    })),
    reducers({
        showCreateModal: [
            false,
            {
                setShowCreateModal: (_, { show }) => show,
            },
        ],
    }),
    selectors({
        canAssignMoreSlots: [
            (s) => [s.slotUsage],
            (slotUsage): boolean => {
                if (!slotUsage) {
                    return false
                }
                // The cap is team-wide, not per-type — read `available` directly.
                return slotUsage.available > 0
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadSlotsSuccess: () => {
            actions.loadSlotUsage()
        },
        setShowCreateModal: ({ show }) => {
            if (show) {
                actions.loadAvailableProperties()
            }
        },
        deleteSlot: async ({ slotId }) => {
            try {
                if (!values.currentTeam) {
                    return
                }
                await api.delete(`api/environments/${values.currentTeam.id}/materialized_column_slots/${slotId}/`)
                lemonToast.success('Slot deleted successfully')
                actions.loadSlots()
            } catch (error) {
                lemonToast.error('Failed to delete slot')
                console.error(error)
            }
        },
        retrySlot: async ({ slotId }) => {
            try {
                if (!values.currentTeam) {
                    return
                }
                await api.create(
                    `api/environments/${values.currentTeam.id}/materialized_column_slots/${slotId}/retry_backfill/`,
                    {}
                )
                lemonToast.success('Slot re-queued — it will be picked up by the next weekly backfill cycle')
                actions.loadSlots()
            } catch (error) {
                lemonToast.error('Failed to re-queue slot')
                console.error(error)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSlots()
            actions.loadAutoMaterializedColumns()
        },
    })),
])
