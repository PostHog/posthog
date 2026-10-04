import { deepEqual } from 'fast-equals'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonDialog, LemonInput, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilterView, DashboardPlacement, DashboardType } from '~/types'

import { DashboardFilterViewsButton } from './DashboardFilterViewsButton'
import {
    createDashboardFilterView,
    DASHBOARD_FILTER_VIEW_PARAM,
    dashboardFilterViewAnalyticsProperties,
    dashboardFilterViewSearchParams,
} from './dashboardFilterViewUtils'
import { dashboardLogic } from './dashboardLogic'
import { parseURLFilters } from './dashboardUtils'

export function DashboardFilterViews(): JSX.Element | null {
    const enabled = useFeatureFlag('DASHBOARD_FILTER_SAVED_VIEWS')
    const { applySavedFilterView } = useActions(dashboardLogic)
    const { dashboard, placement, canEditDashboard, effectiveEditBarFilters, urlFilters } = useValues(dashboardLogic)
    const [saving, setSaving] = useState(false)

    if (!enabled || !dashboard || placement !== DashboardPlacement.Dashboard) {
        return null
    }

    const views = dashboard.customization?.filter_views ?? []
    const selectedId = router.values.searchParams[DASHBOARD_FILTER_VIEW_PARAM]
    const activeView =
        views.find((view) => view.id === selectedId) ?? views.find((view) => deepEqual(view.filters, urlFilters))
    const hasUnsavedChanges = activeView != null && !deepEqual(activeView.filters, effectiveEditBarFilters)

    const saveViews = async (filterViews: DashboardFilterView[]): Promise<void> => {
        if (saving) {
            return
        }
        setSaving(true)
        try {
            const updated = await api.update<DashboardType>(
                `api/environments/${teamLogic.values.currentTeamId}/dashboards/${dashboard.id}`,
                { filter_views: filterViews }
            )
            dashboardsModel.actions.updateDashboardSuccess(getQueryBasedDashboard(updated))
        } catch (error) {
            lemonToast.error('Could not save the view. Try again.')
            throw error
        } finally {
            setSaving(false)
        }
    }

    const selectView = (view: DashboardFilterView): void => {
        const { currentLocation } = router.values
        if (activeView?.id !== view.id || hasUnsavedChanges) {
            posthog.capture('dashboard filter view applied', {
                dashboard_id: dashboard.id,
                saved_view_count: views.length,
                ...dashboardFilterViewAnalyticsProperties(view.filters),
            })
        }
        const searchParams = dashboardFilterViewSearchParams(currentLocation.searchParams, activeView?.id, view)
        applySavedFilterView(parseURLFilters(searchParams))
        router.actions.push(currentLocation.pathname, searchParams, currentLocation.hashParams)
    }

    const createView = (): void => {
        if (saving) {
            return
        }
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
                saveViews([...views, createDashboardFilterView(crypto.randomUUID(), name, effectiveEditBarFilters)]),
            primaryButtonProps: { children: 'Save view' },
        })
    }

    const editView = (view: DashboardFilterView): void => {
        LemonDialog.openForm({
            title: 'Rename view',
            initialValues: { name: view.name },
            content: (
                <LemonField name="name" label="Name">
                    <LemonInput autoFocus />
                </LemonField>
            ),
            errors: { name: (name) => (!name?.trim() ? 'Enter a view name' : undefined) },
            onSubmit: ({ name }) =>
                saveViews(
                    views.map((candidate) =>
                        candidate.id === view.id ? { ...candidate, name: name.trim() } : candidate
                    )
                ),
            primaryButtonProps: { children: 'Save name' },
        })
    }

    const saveChanges = async (view: DashboardFilterView): Promise<void> => {
        if (!hasUnsavedChanges) {
            return
        }
        try {
            await saveViews(
                views.map((candidate) =>
                    candidate.id === view.id ? { ...candidate, filters: effectiveEditBarFilters } : candidate
                )
            )
            lemonToast.success('View updated')
        } catch {
            return
        }
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
        <DashboardFilterViewsButton
            views={views}
            activeView={activeView}
            hasUnsavedChanges={hasUnsavedChanges}
            saving={saving}
            canEdit={canEditDashboard}
            onCreate={createView}
            onSelect={selectView}
            onDelete={deleteView}
            onEdit={editView}
            onSaveChanges={(view) => void saveChanges(view)}
        />
    )
}
