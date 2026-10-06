import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { cn } from 'lib/utils/css-classes'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

import { SavedInsightsQuickFilters } from './SavedInsightsQuickFilters'

export type QuickFilterKind = 'insightType' | 'tags' | 'createdBy' | 'favorites'
const ALL_QUICK_FILTERS: QuickFilterKind[] = ['insightType', 'tags', 'createdBy', 'favorites']

export function SavedInsightsFilters({
    filters,
    setFilters,
    quickFilters = ALL_QUICK_FILTERS,
    borderless = false,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    quickFilters?: QuickFilterKind[]
    /** When true, inactive filters appear borderless. */
    borderless?: boolean
}): JSX.Element {
    const { search } = filters

    return (
        <div className={cn('flex justify-between gap-2 items-center flex-wrap')}>
            <LemonInput
                type="search"
                placeholder="Search for insights"
                onChange={(value) => setFilters({ search: value })}
                value={search || ''}
                autoFocus
                data-attr="insight-dashboard-modal-search"
            />
            {quickFilters.length > 0 && (
                <SavedInsightsQuickFilters
                    filters={filters}
                    setFilters={setFilters}
                    quickFilters={quickFilters}
                    borderless={borderless}
                />
            )}
        </div>
    )
}
