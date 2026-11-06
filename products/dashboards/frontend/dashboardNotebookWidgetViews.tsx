import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { DashboardPlacement } from '~/types'

export type DashboardNotebookWidgetAttributes = {
    id: number
    view?: string
}

function DashboardMetadata({ attributes }: NotebookNodeProps<DashboardNotebookWidgetAttributes>): null {
    const { dashboard } = useValues(dashboardLogic({ id: attributes.id, placement: DashboardPlacement.Builtin }))
    const { setTitlePlaceholder } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(dashboard?.name || 'Dashboard')
    }, [dashboard?.name, setTitlePlaceholder])

    return null
}

function DashboardSummary({ attributes }: NotebookNodeProps<DashboardNotebookWidgetAttributes>): JSX.Element {
    const { dashboard, itemsLoading, tiles } = useValues(
        dashboardLogic({ id: attributes.id, placement: DashboardPlacement.Builtin })
    )

    if (!dashboard && itemsLoading) {
        return (
            <div className="p-3">
                <LemonSkeleton className="h-6 w-full" />
            </div>
        )
    }
    if (!dashboard) {
        return <NotFound object="dashboard" />
    }

    const insightCount = tiles?.length || 0

    return (
        <>
            <DashboardMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="flex flex-wrap items-center gap-2 p-3">
                <span className="min-w-48 flex-1 truncate">{dashboard.description || 'No description'}</span>
                {dashboard.is_shared ? <LemonTag type="muted">Shared</LemonTag> : null}
                <span className="text-xs text-secondary">
                    {insightCount} {insightCount === 1 ? 'insight' : 'insights'}
                </span>
            </div>
        </>
    )
}

export function DashboardDetail({ attributes }: NotebookNodeProps<DashboardNotebookWidgetAttributes>): JSX.Element {
    return (
        <>
            <DashboardMetadata attributes={attributes} updateAttributes={() => {}} />
            <div className="max-h-[48rem] overflow-auto">
                <Dashboard id={String(attributes.id)} placement={DashboardPlacement.Builtin} />
            </div>
        </>
    )
}

export const DASHBOARD_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<
    DashboardNotebookWidgetAttributes,
    'Dashboard'
>('Dashboard', {
    summary: DashboardSummary,
})
