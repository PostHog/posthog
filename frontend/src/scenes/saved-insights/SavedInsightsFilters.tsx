import posthog from 'posthog-js'

import { IconHeart, IconHeartFilled } from '@posthog/icons'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { cn } from 'lib/utils/css-classes'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

import { SavedInsightsTagSelect } from './SavedInsightsTagSelect'

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
    const { search, favorited, tags, insightType, createdBy } = filters
    const quickFilterSet = new Set(quickFilters)
    const hasInsightTypeSelection = !!insightType && insightType !== 'All types'

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
                <div className="flex gap-2 items-center flex-wrap ml-auto">
                    {quickFilterSet.has('insightType') && (
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            size="small"
                            active={hasInsightTypeSelection}
                            status={borderless && !hasInsightTypeSelection ? 'alt' : 'default'}
                            onChange={(value) => {
                                setFilters({ insightType: value as string })
                                posthog.capture('saved insights filtered', { filter_type: 'insight_type', value })
                            }}
                            options={INSIGHT_TYPE_OPTIONS}
                            value={insightType || 'All types'}
                        />
                    )}
                    {quickFilterSet.has('tags') && (
                        <SavedInsightsTagSelect
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
                        <LemonButton
                            type="secondary"
                            status={borderless && !favorited ? 'alt' : 'default'}
                            active={favorited || false}
                            onClick={() => setFilters({ favorited: !favorited })}
                            size="small"
                            icon={
                                favorited ? (
                                    <IconHeartFilled className="text-danger" />
                                ) : (
                                    <IconHeart className="text-secondary" />
                                )
                            }
                        >
                            Favorites
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
