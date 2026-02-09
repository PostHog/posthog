import { useActions, useValues } from 'kea'
import { actions, kea, path, props, reducers, selectors } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonModal, lemonToast } from '@posthog/lemon-ui'

import { QuickFilterForm } from 'lib/components/QuickFilters/QuickFilterForm'
import { QuickFiltersModalContent } from 'lib/components/QuickFilters/QuickFiltersModalContent'
import { ModalView, quickFiltersModalLogic } from 'lib/components/QuickFilters/quickFiltersModalLogic'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { DashboardType } from '~/types'

export interface DashboardQuickFiltersSelectionLogicProps {
    dashboard: DashboardType<any>
}

export const dashboardQuickFiltersSelectionLogic = kea([
    path(['scenes', 'dashboard', 'dashboardQuickFiltersSelectionLogic']),
    props({} as DashboardQuickFiltersSelectionLogicProps),

    actions({
        toggleDashboardFilter: (filterId: string) => ({ filterId }),
        setSelectedDashboardFilterIds: (filterIds: string[]) => ({ filterIds }),
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

    selectors({
        hasDashboardSelectionChanges: [
            (s, p) => [s.selectedDashboardFilterIds, () => p.dashboard.quick_filter_ids ?? []],
            (selectedIds: string[], dashboardIds: string[]): boolean => {
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

interface DashboardQuickFiltersButtonProps {
    context: QuickFilterContext
    dashboard: DashboardType<any>
    updateDashboard: (payload: Partial<DashboardType<any>>) => void
}

export function DashboardQuickFiltersButton({
    context,
    dashboard,
    updateDashboard,
}: DashboardQuickFiltersButtonProps): JSX.Element {
    const modalLogicProps = { context, modalKey: dashboard.id }
    const modalLogic = quickFiltersModalLogic(modalLogicProps)
    const { openModal, closeModal } = useActions(modalLogic)
    const { isModalOpen, view, modalTitle } = useValues(modalLogic)

    const selectionLogic = dashboardQuickFiltersSelectionLogic({ dashboard })
    const { selectedDashboardFilterIds, hasDashboardSelectionChanges } = useValues(selectionLogic)
    const { toggleDashboardFilter, setSelectedDashboardFilterIds } = useActions(selectionLogic)

    const handleSaveSelection = (): void => {
        updateDashboard({ quick_filter_ids: selectedDashboardFilterIds })
        lemonToast.success('Dashboard quick filters updated')
        closeModal()
    }

    const handleNewFilterCreated = (filter: { id: string }): void => {
        if (!selectedDashboardFilterIds.includes(filter.id)) {
            const newIds = [...selectedDashboardFilterIds, filter.id]
            setSelectedDashboardFilterIds(newIds)
            updateDashboard({ quick_filter_ids: newIds })
        }
    }

    // Wire the generic modal logic's callback to auto-select newly created filters
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useActions(quickFiltersModalLogic({ context, modalKey: dashboard.id, onNewFilterCreated: handleNewFilterCreated }))

    return (
        <>
            <LemonButton
                size="small"
                icon={<IconFilter />}
                onClick={openModal}
                tooltip="Configure quick filters"
                aria-label="Configure quick filters"
            />
            <LemonModal title={modalTitle} isOpen={isModalOpen} onClose={closeModal} width={800}>
                {view === ModalView.List ? (
                    <QuickFiltersModalContent
                        context={context}
                        modalKey={dashboard.id}
                        selectionColumnConfig={{
                            selectedIds: selectedDashboardFilterIds,
                            onToggleId: toggleDashboardFilter,
                        }}
                        footerActionsConfig={{
                            onSaveSelection: handleSaveSelection,
                            hasChanges: hasDashboardSelectionChanges,
                        }}
                    />
                ) : (
                    <QuickFilterForm context={context} modalKey={dashboard.id} />
                )}
            </LemonModal>
        </>
    )
}
