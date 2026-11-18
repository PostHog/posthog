import posthog from 'posthog-js'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { TagSelect } from 'lib/components/TagSelect'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

import { SavedInsightsFavoriteFilter } from './SavedInsightsFavoriteFilter'
import { QuickFilterKind } from './SavedInsightsFilters'
import { SavedInsightsTypeFilter } from './SavedInsightsTypeFilter'

type SetFilters = (filters: Partial<SavedInsightFilters>) => void

export function SavedInsightsQuickFilters({
    filters,
    setFilters,
    quickFilters,
    borderless,
}: {
    filters: SavedInsightFilters
    setFilters: SetFilters
    quickFilters: QuickFilterKind[]
    borderless: boolean
}): JSX.Element {
    const { favorited, tags, insightType, createdBy } = filters
    const quickFilterSet = new Set(quickFilters)

    return (
        <div className="flex gap-2 items-center flex-wrap ml-auto">
            {quickFilterSet.has('insightType') && (
                <SavedInsightsTypeFilter insightType={insightType} setFilters={setFilters} borderless={borderless} />
            )}
            {quickFilterSet.has('tags') && (
                <TagSelect
                    defaultLabel="Tags"
                    listDataAttr="saved-insights-tags-list"
                    value={tags || []}
                    borderless={borderless}
                    onChange={(tags) => {
                        setFilters({ tags: tags.length > 0 ? tags : [] })
                        posthog.capture('saved insights filtered', { filter_type: 'tags', value: tags })
                    }}
                />
            )}
            {quickFilterSet.has('createdBy') && (
                <MemberSelectMultiplePopover
                    value={createdBy !== 'All users' ? (createdBy as number[]) : []}
                    onChange={(ids) => {
                        const createdByValue = ids.length > 0 ? ids : 'All users'
                        setFilters({ createdBy: createdByValue })
                        posthog.capture('saved insights filtered', {
                            filter_type: 'created_by',
                            value: createdByValue,
                        })
                    }}
                    borderless={borderless}
                />
            )}
            {quickFilterSet.has('favorites') && (
                <SavedInsightsFavoriteFilter favorited={favorited} setFilters={setFilters} borderless={borderless} />
            )}
        </div>
    )
}
