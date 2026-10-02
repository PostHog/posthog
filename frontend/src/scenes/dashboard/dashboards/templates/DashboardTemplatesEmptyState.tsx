import { LemonButton } from '@posthog/lemon-ui'

import { openNewDashboardGallery } from './dashboardTemplateCreationFlows'

export function DashboardTemplatesEmptyState({
    isStaff,
    searchText,
    filtered,
    onClearFilters,
}: {
    isStaff: boolean
    searchText: string | null
    filtered: boolean
    onClearFilters: () => void
}): JSX.Element {
    if (!filtered) {
        return (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
                <h3 className="m-0 text-base font-semibold">No templates yet</h3>
                <p className="m-0 max-w-md text-secondary">
                    Open any dashboard and choose <b>Save as dashboard template</b>. It will show up here.
                </p>
                <LemonButton
                    type="secondary"
                    className="mt-2"
                    onClick={openNewDashboardGallery}
                    data-attr="dashboard-templates-empty-browse-official"
                >
                    Browse PostHog templates
                </LemonButton>
            </div>
        )
    }
    return (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
            <h3 className="m-0 text-base font-semibold">
                {searchText ? `No templates match "${searchText}"` : 'No templates match this filter'}
            </h3>
            {isStaff ? null : (
                <p className="m-0 text-secondary">
                    PostHog's templates are under <b>New dashboard</b>.
                </p>
            )}
            <LemonButton
                type="secondary"
                className="mt-2"
                onClick={onClearFilters}
                data-attr="dashboard-templates-empty-clear-filters"
            >
                Clear filters
            </LemonButton>
        </div>
    )
}
