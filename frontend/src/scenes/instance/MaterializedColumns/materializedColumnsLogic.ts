import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
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

export interface Team {
    id: number
    name: string
}

export const materializedColumnsLogic = kea<materializedColumnsLogicType>([
    path(['scenes', 'instance', 'MaterializedColumns', 'materializedColumnsLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions({
        setSelectedTeamId: (teamId: number | null) => ({ teamId }),
        setShowCreateModal: (show: boolean) => ({ show }),
        deleteSlot: (slotId: string) => ({ slotId }),
    }),
    loaders(({ values }) => ({
        slots: [
            [] as MaterializedColumnSlot[],
            {
                loadSlots: async () => {
                    if (!values.selectedTeamId) {
                        return []
                    }
                    const response = await api.get(`api/materialized_column_slots/?team_id=${values.selectedTeamId}`)
                    return response.results || []
                },
            },
        ],
        slotUsage: [
            null as SlotUsageSummary | null,
            {
                loadSlotUsage: async () => {
                    if (!values.selectedTeamId) {
                        return null
                    }
                    return await api.get(`api/materialized_column_slots/slot_usage/?team_id=${values.selectedTeamId}`)
                },
            },
        ],
        availableProperties: [
            [] as PropertyDefinition[],
            {
                loadAvailableProperties: async () => {
                    if (!values.selectedTeamId) {
                        return []
                    }
                    return await api.get(
                        `api/materialized_column_slots/available_properties/?team_id=${values.selectedTeamId}`
                    )
                },
            },
        ],
        teams: [
            [] as Team[],
            {
                loadTeams: async () => {
                    const response = await api.get('api/organizations/@current/teams/')
                    return response.results || []
                },
            },
        ],
    })),
    reducers({
        selectedTeamId: [
            null as number | null,
            {
                setSelectedTeamId: (_, { teamId }) => teamId,
            },
        ],
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
        setSelectedTeamId: () => {
            actions.loadSlots()
            actions.loadSlotUsage()
        },
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
            actions.loadTeams()
        },
    })),
])
