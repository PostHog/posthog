import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    DEFAULT_SIDEBAR_CARD_LAYOUT,
    moveSidebarRow,
    normalizeSidebarLayout,
    SidebarCardLayout,
    TicketSidebarCardRowId,
    toggleSidebarRow,
} from './ticketSidebarLayout'

export interface ticketSidebarLayoutLogicValues {
    isLayoutModalOpen: boolean
    userLayout: SidebarCardLayout | null
    draftLayout: SidebarCardLayout
    teamLayout: SidebarCardLayout | null
    effectiveLayout: SidebarCardLayout
    hasUserOverride: boolean
    isCustomized: boolean
    hiddenRowIds: TicketSidebarCardRowId[]
    visibleRows: SidebarCardLayout
}

export interface ticketSidebarLayoutLogicActions {
    setLayoutModalOpen: (open: boolean) => { open: boolean }
    setDraftLayout: (layout: SidebarCardLayout) => { layout: SidebarCardLayout }
    moveDraftRow: (fromIndex: number, toIndex: number) => { fromIndex: number; toIndex: number }
    toggleDraftRowVisibility: (rowId: TicketSidebarCardRowId) => { rowId: TicketSidebarCardRowId }
    setUserLayout: (layout: SidebarCardLayout | null) => { layout: SidebarCardLayout | null }
    saveDraftLayout: () => void
    resetUserLayout: () => void
    saveAsTeamDefault: () => void
    resetTeamDefault: () => void
    loadUserLayout: () => void
}

export type ticketSidebarLayoutLogicType = MakeLogicType<
    ticketSidebarLayoutLogicValues,
    ticketSidebarLayoutLogicActions
>

function getStorageKey(teamId: string | number | undefined): string {
    return `posthog-conversations-ticket-sidebar-card-layout-${teamId ?? 'default'}`
}

function readStoredUserLayout(teamId: string | number | undefined): SidebarCardLayout | null {
    if (typeof localStorage === 'undefined') {
        return null
    }
    try {
        const item = localStorage.getItem(getStorageKey(teamId))
        if (!item) {
            return null
        }
        const parsed = JSON.parse(item)
        return normalizeSidebarLayout(parsed)
    } catch {
        return null
    }
}

function writeStoredUserLayout(teamId: string | number | undefined, layout: SidebarCardLayout | null): void {
    if (typeof localStorage === 'undefined') {
        return
    }
    try {
        const key = getStorageKey(teamId)
        if (layout === null) {
            localStorage.removeItem(key)
        } else {
            localStorage.setItem(key, JSON.stringify(layout))
        }
    } catch {
        // Storage full or unavailable
    }
}

export const ticketSidebarLayoutLogic = kea<ticketSidebarLayoutLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'ticketSidebarLayoutLogic']),
    connect({
        values: [teamLogic, ['currentTeam'], userLogic, ['user']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        setLayoutModalOpen: (open: boolean) => ({ open }),
        setDraftLayout: (layout: SidebarCardLayout) => ({ layout }),
        moveDraftRow: (fromIndex: number, toIndex: number) => ({ fromIndex, toIndex }),
        toggleDraftRowVisibility: (rowId: TicketSidebarCardRowId) => ({ rowId }),
        setUserLayout: (layout: SidebarCardLayout | null) => ({ layout }),
        saveDraftLayout: true,
        resetUserLayout: true,
        saveAsTeamDefault: true,
        resetTeamDefault: true,
        loadUserLayout: true,
    }),
    reducers({
        isLayoutModalOpen: [
            false,
            {
                setLayoutModalOpen: (_, { open }) => open,
            },
        ],
        userLayout: [
            null as SidebarCardLayout | null,
            {
                setUserLayout: (_, { layout }) => layout,
            },
        ],
        draftLayout: [
            DEFAULT_SIDEBAR_CARD_LAYOUT,
            {
                setDraftLayout: (_, { layout }) => layout,
                moveDraftRow: (state, { fromIndex, toIndex }) => moveSidebarRow(state, fromIndex, toIndex),
                toggleDraftRowVisibility: (state, { rowId }) => toggleSidebarRow(state, rowId),
            },
        ],
    }),
    selectors({
        teamLayout: [
            (s) => [s.currentTeam],
            (currentTeam): SidebarCardLayout | null => {
                const raw = currentTeam?.conversations_settings?.ticket_sidebar_card_layout
                return raw ? normalizeSidebarLayout(raw) : null
            },
        ],
        effectiveLayout: [
            (s) => [s.userLayout, s.teamLayout],
            (userLayout, teamLayout): SidebarCardLayout => {
                if (userLayout) {
                    return userLayout
                }
                if (teamLayout) {
                    return teamLayout
                }
                return DEFAULT_SIDEBAR_CARD_LAYOUT
            },
        ],
        hasUserOverride: [(s) => [s.userLayout], (userLayout) => !!userLayout],
        isCustomized: [
            (s) => [s.effectiveLayout],
            (effectiveLayout) =>
                JSON.stringify(effectiveLayout) !== JSON.stringify(DEFAULT_SIDEBAR_CARD_LAYOUT),
        ],
        hiddenRowIds: [
            (s) => [s.effectiveLayout],
            (effectiveLayout) =>
                effectiveLayout.filter((row) => !row.visible).map((row) => row.id),
        ],
        visibleRows: [
            (s) => [s.effectiveLayout],
            (effectiveLayout) => effectiveLayout.filter((row) => row.visible),
        ],
    }),
    listeners(({ actions, values }) => ({
        setLayoutModalOpen: ({ open }) => {
            if (open) {
                actions.setDraftLayout(values.effectiveLayout)
            }
        },
        toggleDraftRowVisibility: ({ rowId }) => {
            const nextRow = values.draftLayout.find((r) => r.id === rowId)
            if (nextRow) {
                posthog.capture('ticket_sidebar_row_visibility_toggled', {
                    row_id: rowId,
                    visible: nextRow.visible,
                })
            }
        },
        moveDraftRow: () => {
            posthog.capture('ticket_sidebar_layout_reordered', {
                order: values.draftLayout.map((r) => r.id),
            })
        },
        saveDraftLayout: () => {
            const layout = values.draftLayout
            writeStoredUserLayout(values.currentTeam?.id, layout)
            actions.setUserLayout(layout)
            actions.setLayoutModalOpen(false)
            posthog.capture('ticket_sidebar_layout_updated', {
                order: layout.map((r) => r.id),
                hidden_rows: layout.filter((r) => !r.visible).map((r) => r.id),
            })
            lemonToast.success('Sidebar card layout saved')
        },
        resetUserLayout: () => {
            writeStoredUserLayout(values.currentTeam?.id, null)
            actions.setUserLayout(null)
            actions.setDraftLayout(values.teamLayout ?? DEFAULT_SIDEBAR_CARD_LAYOUT)
            posthog.capture('ticket_sidebar_layout_reset', {
                team_id: values.currentTeam?.id,
            })
            lemonToast.info('Sidebar layout reset')
        },
        saveAsTeamDefault: () => {
            const layoutToSave = values.draftLayout
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    ticket_sidebar_card_layout: layoutToSave,
                },
            })
            posthog.capture('ticket_sidebar_layout_saved_as_team_default', {
                team_id: values.currentTeam?.id,
                order: layoutToSave.map((r) => r.id),
                hidden_rows: layoutToSave.filter((r) => !r.visible).map((r) => r.id),
            })
            lemonToast.success('Saved as default sidebar layout for your team')
        },
        resetTeamDefault: () => {
            actions.updateCurrentTeam({
                conversations_settings: {
                    ...values.currentTeam?.conversations_settings,
                    ticket_sidebar_card_layout: null,
                },
            })
            posthog.capture('ticket_sidebar_layout_team_default_reset', {
                team_id: values.currentTeam?.id,
            })
            lemonToast.info('Team default layout reset to system default')
        },
        loadUserLayout: () => {
            const stored = readStoredUserLayout(values.currentTeam?.id)
            actions.setUserLayout(stored)
        },
    })),
])
