import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { quickFiltersModalLogic } from 'lib/components/QuickFilters/quickFiltersModalLogic'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { DashboardType } from '~/types'

import { dashboardLogic } from './dashboardLogic'
import type { dashboardQuickFiltersSelectionLogicType } from './dashboardQuickFiltersSelectionLogicType'

export interface DashboardQuickFiltersSelectionLogicProps {
    dashboard: DashboardType<any>
}

export const dashboardQuickFiltersSelectionLogic = kea<dashboardQuickFiltersSelectionLogicType>([
    path(['scenes', 'dashboard', 'dashboardQuickFiltersSelectionLogic']),
    props({} as DashboardQuickFiltersSelectionLogicProps),
    key((props) => props.dashboard.id),

    connect((props: DashboardQuickFiltersSelectionLogicProps) => ({
        values: [dashboardLogic({ id: props.dashboard.id }), ['dashboard']],
        actions: [
            dashboardLogic({ id: props.dashboard.id }),
            ['triggerDashboardUpdate'],
            quickFiltersModalLogic({ context: QuickFilterContext.Dashboards }),
            ['openModal', 'closeModal', 'newFilterCreated'],
        ],
    })),

    actions({
        toggleDashboardFilter: (filterId: string) => ({ filterId }),
        setSelectedDashboardFilterIds: (filterIds: string[]) => ({ filterIds }),
        addNewFilter: (filterId: string) => ({ filterId }),
        openConfigureModal: true,
        saveAndCloseModal: true,
        cancelModal: true,
        syncFromDashboard: true,
    }),

    reducers(({ props }) => ({
        selectedDashboardFilterIds: [
            props.dashboard.quick_filter_ids ?? [],
            {
                toggleDashboardFilter: (state: string[], { filterId }: { filterId: string }) =>
                    state.includes(filterId) ? state.filter((id: string) => id !== filterId) : [...state, filterId],
                setSelectedDashboardFilterIds: (_: string[], { filterIds }: { filterIds: string[] }) => filterIds,
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        syncFromDashboard: () => {
            actions.setSelectedDashboardFilterIds(values.dashboard?.quick_filter_ids ?? [])
        },
        newFilterCreated: ({ filter }) => {
            actions.addNewFilter(filter.id)
        },
        addNewFilter: ({ filterId }) => {
            if (!values.selectedDashboardFilterIds.includes(filterId)) {
                actions.setSelectedDashboardFilterIds([...values.selectedDashboardFilterIds, filterId])
            }
        },
        openConfigureModal: () => {
            actions.syncFromDashboard()
            actions.openModal()
        },
        saveAndCloseModal: () => {
            actions.triggerDashboardUpdate({ quick_filter_ids: values.selectedDashboardFilterIds })
            lemonToast.success('Dashboard quick filters updated')
            actions.closeModal()
        },
        cancelModal: () => {
            actions.syncFromDashboard()
            actions.closeModal()
        },
    })),

    selectors({
        hasDashboardSelectionChanges: [
            (s) => [s.selectedDashboardFilterIds, s.dashboard],
            (selectedIds: string[], dashboard: DashboardType<any> | null): boolean => {
                const dashboardIds = dashboard?.quick_filter_ids ?? []
                if (selectedIds.length !== dashboardIds.length) {
                    return true
                }
                const sortedSelected = [...selectedIds].sort()
                const sortedDashboard = [...dashboardIds].sort()
                return !sortedSelected.every((id, index) => id === sortedDashboard[index])
            },
        ],
    }),
])
