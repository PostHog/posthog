import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { QuickFilterForm } from 'lib/components/QuickFilters/QuickFilterForm'
import { QuickFiltersModalContent } from 'lib/components/QuickFilters/QuickFiltersModalContent'
import { ModalView, quickFiltersModalLogic } from 'lib/components/QuickFilters/quickFiltersModalLogic'
import { Scene } from 'scenes/sceneTypes'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { DashboardType } from '~/types'

import { dashboardQuickFiltersSelectionLogic } from './dashboardQuickFiltersSelectionLogic'

interface DashboardQuickFiltersButtonProps {
    context: QuickFilterContext
    dashboard: DashboardType<any>
}

export function DashboardQuickFiltersButton({ context, dashboard }: DashboardQuickFiltersButtonProps): JSX.Element {
    const selectionLogic = dashboardQuickFiltersSelectionLogic({ dashboard })
    const { selectedDashboardFilterIds, hasDashboardSelectionChanges } = useValues(selectionLogic)
    const { toggleDashboardFilter, openConfigureModal, saveAndCloseModal, cancelModal } = useActions(selectionLogic)
    const modalLogic = quickFiltersModalLogic({ context })
    const { isModalOpen, view, modalTitle } = useValues(modalLogic)

    return (
        <>
            <AppShortcut
                name="DashboardQuickFilters"
                keybind={[['f']]}
                intent="Quick filters"
                interaction="click"
                scope={Scene.Dashboard}
            >
                <LemonButton
                    size="small"
                    icon={<IconGear />}
                    onClick={openConfigureModal}
                    tooltip="Configure quick filters"
                    aria-label="Configure quick filters"
                >
                    {selectedDashboardFilterIds.length === 0 ? 'Configure quick filters' : undefined}
                </LemonButton>
            </AppShortcut>
            <LemonModal
                title={modalTitle}
                isOpen={isModalOpen}
                onClose={cancelModal}
                hasUnsavedInput={hasDashboardSelectionChanges}
                width={800}
            >
                {view === ModalView.List ? (
                    <QuickFiltersModalContent
                        context={context}
                        selectionColumnConfig={{
                            selectedIds: selectedDashboardFilterIds,
                            onToggleId: toggleDashboardFilter,
                        }}
                        footerActionsConfig={{
                            onSaveSelection: saveAndCloseModal,
                            hasChanges: hasDashboardSelectionChanges,
                        }}
                    />
                ) : (
                    <QuickFilterForm context={context} />
                )}
            </LemonModal>
        </>
    )
}
