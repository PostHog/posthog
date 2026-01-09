import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { materializedColumnsLogicType } from './materializedColumnsLogicType'

export enum MaterializedColumnSlotState {
    BACKFILL = 'BACKFILL',
    READY = 'READY',
    ERROR = 'ERROR',
}

export enum MaterializationType {
    DMAT = 'dmat',
    EAV = 'eav',
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
    property_name: string
    property_type: string
    slot_index: number
    state: MaterializedColumnSlotState
    materialization_type: MaterializationType
    backfill_temporal_uuid: string | null
    created_at: string
    updated_at: string
}

export interface SlotUsageSummary {
    team_id: number
    team_name: string
    usage: {
        [key: string]: {
            used: number
            total: number
            available: number
        }
    }
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
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions({
        setShowCreateModal: (show: boolean) => ({ show }),
        deleteSlot: (slotId: string) => ({ slotId }),
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
                return Object.values(slotUsage.usage).some(
                    (usage: { used: number; total: number; available: number }) => usage.available > 0
                )
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
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSlots()
            actions.loadAutoMaterializedColumns()
        },
    })),
])
