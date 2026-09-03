import { deepEqual } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconChevronDown, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, Popover } from '@posthog/lemon-ui'

import { SavedViewsList } from 'lib/components/SavedViews/SavedViewsList'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DashboardFilterView, DashboardPlacement } from '~/types'

import { dashboardLogic } from './dashboardLogic'
import { searchParamsWithUrlFilters } from './dashboardUtils'

export function DashboardFilterViews(): JSX.Element | null {
    const enabled = useFeatureFlag('DASHBOARD_FILTER_SAVED_VIEWS')
    const { dashboard, placement, canEditDashboard, effectiveEditBarFilters, urlFilters } = useValues(dashboardLogic)
    const { triggerDashboardUpdate } = useActions(dashboardLogic)
    const [visible, setVisible] = useState(false)

    if (!enabled || !dashboard || placement !== DashboardPlacement.Dashboard) {
        return null
    }

    const views = dashboard.customization?.filter_views ?? []
    const activeView = views.find((view) => deepEqual(view.filters, urlFilters))

    const saveViews = (filterViews: DashboardFilterView[]): void => {
        triggerDashboardUpdate({ filter_views: filterViews })
    }

    const selectView = (view: DashboardFilterView): void => {
        const { currentLocation } = router.values
        const filters = activeView?.id === view.id ? {} : view.filters
        router.actions.push(
            currentLocation.pathname,
            searchParamsWithUrlFilters(currentLocation.searchParams, filters),
            currentLocation.hashParams
        )
        setVisible(false)
    }

    const createView = (): void => {
        LemonDialog.openForm({
            title: 'Save filter view',
            initialValues: { name: '' },
            content: (
                <LemonField name="name" label="Name">
                    <LemonInput autoFocus placeholder="Enter a view name" />
                </LemonField>
            ),
            errors: { name: (name) => (!name?.trim() ? 'Enter a view name' : undefined) },
            onSubmit: ({ name }) =>
                saveViews([...views, { id: crypto.randomUUID(), name: name.trim(), filters: effectiveEditBarFilters }]),
            primaryButtonProps: { children: 'Save view' },
        })
    }

    const deleteView = (view: DashboardFilterView): void => {
        LemonDialog.open({
            title: `Delete “${view.name}”?`,
            description: 'This removes the view from this dashboard.',
            primaryButton: {
                children: 'Delete view',
                status: 'danger',
                onClick: () => saveViews(views.filter((candidate) => candidate.id !== view.id)),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <Popover
            visible={visible}
            padded={false}
            onClickOutside={() => setVisible(false)}
            overlay={
                <div className="flex w-72 flex-col py-1" data-attr="dashboard-filter-views-popover">
                    {canEditDashboard && views.length < 20 && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="tertiary"
                            className="justify-start rounded-none px-3"
                            icon={<IconPlus />}
                            onClick={createView}
                        >
                            Save current filters
                        </LemonButton>
                    )}
                    {canEditDashboard && views.length < 20 && <div className="border-t" />}
                    <SavedViewsList
                        views={[...views].sort((left, right) => left.name.localeCompare(right.name))}
                        activeViewId={activeView?.id}
                        emptyMessage="No saved filter views yet."
                        onSelect={selectView}
                        onDelete={canEditDashboard ? deleteView : undefined}
                    />
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                data-attr="dashboard-filter-views-picker"
                sideIcon={<IconChevronDown />}
                onClick={() => setVisible(!visible)}
            >
                {activeView?.name ?? 'Views'}
            </LemonButton>
        </Popover>
    )
}
