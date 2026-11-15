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
                // A customer's search can't match PostHog's templates here, so point them to where those live.
                searchText && !isStaff
                    ? "PostHog's templates are under New dashboard."
                    : 'Clear the filters to see every template.'
            }
            buttonText="Clear filters"
            buttonOnClick={onClearFilters}
            buttonDataAttr="dashboard-templates-empty-clear-filters"
        />
    )
}
