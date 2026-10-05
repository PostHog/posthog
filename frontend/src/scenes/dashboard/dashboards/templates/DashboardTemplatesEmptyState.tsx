import { router } from 'kea-router'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { urls } from 'scenes/urls'

export interface DashboardTemplatesEmptyStateProps {
    isStaff: boolean
    searchText: string | null
    hasActiveFilters: boolean
    loadFailed: boolean
    onClearFilters: () => void
    onRetry: () => void
}

/** Drops `templates` so the manage modal closes, and `templateFilter` so its search does not filter the gallery. */
function openNewDashboardGallery(): void {
    const { templates: _templates, templateFilter: _templateFilter, ...searchParams } = router.values.searchParams
    router.actions.push(urls.dashboards(), searchParams, { newDashboard: 'modal' })
}

export function DashboardTemplatesEmptyState({
    isStaff,
    searchText,
    hasActiveFilters,
    loadFailed,
    onClearFilters,
    onRetry,
}: DashboardTemplatesEmptyStateProps): JSX.Element {
    if (loadFailed) {
        return (
            <EmptyMessage
                title="Couldn't load templates"
                description="The request failed. Try again, and contact support if it keeps happening."
                buttonText="Try again"
                buttonOnClick={onRetry}
                buttonDataAttr="dashboard-templates-empty-retry"
            />
        )
    }
    if (!hasActiveFilters) {
        return (
            <EmptyMessage
                title="No templates yet"
                description='Open a dashboard and choose "Save as dashboard template" to add one here.'
                buttonText="Browse PostHog templates"
                buttonOnClick={openNewDashboardGallery}
                buttonDataAttr="dashboard-templates-empty-browse-official"
            />
        )
    }
    return (
        <EmptyMessage
            title={searchText ? `No templates match "${searchText}"` : 'No templates match this filter'}
            description={
                isStaff ? 'Clear the filters to see every template.' : "PostHog's templates are under New dashboard."
            }
            buttonText="Clear filters"
            buttonOnClick={onClearFilters}
            buttonDataAttr="dashboard-templates-empty-clear-filters"
        />
    )
}
