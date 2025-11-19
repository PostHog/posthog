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
    property_type: string
    slot_index: number
    state: MaterializedColumnSlotState
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
                    const response = await api.get(`api/materialized_column_slots/?team_id=${values.currentTeam.id}`)
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
                    return await api.get(`api/materialized_column_slots/slot_usage/?team_id=${values.currentTeam.id}`)
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
                        `api/materialized_column_slots/available_properties/?team_id=${values.currentTeam.id}`
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
                return Object.values(slotUsage.usage).some((usage) => usage.available > 0)
            },
        ],
    }),
    listeners(({ actions }) => ({
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
                await api.delete(`api/materialized_column_slots/${slotId}/`)
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
            actions.loadSlotUsage()
        },
    })),
])
