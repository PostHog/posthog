import posthog from 'posthog-js'

import { IconFlag, IconHeart, IconHeartFilled, IconSort } from '@posthog/icons'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { TagSelect } from 'lib/components/TagSelect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/insightTypesMetadata'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

export type QuickFilterKind = 'insightType' | 'tags' | 'createdBy' | 'favorites' | 'featureFlags' | 'sort'
const ALL_QUICK_FILTERS: QuickFilterKind[] = ['insightType', 'tags', 'createdBy', 'favorites', 'featureFlags']

/** Values map straight onto the API's `order` param. */
export const INSIGHT_SORT_OPTIONS: LemonSelectOptions<string> = [
    { value: '-last_modified_at', label: 'Last modified' },
    { value: '-created_at', label: 'Newest' },
    { value: 'created_at', label: 'Oldest' },
    { value: '-last_viewed_at', label: 'Recently viewed' },
    { value: 'name', label: 'Name A-Z' },
    { value: '-name', label: 'Name Z-A' },
]

export function SavedInsightsFilters({
    filters,
    setFilters,
    quickFilters = ALL_QUICK_FILTERS,
    borderless = false,
    showSearch = true,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
    quickFilters?: QuickFilterKind[]
    /** When true, inactive filters appear borderless. */
    borderless?: boolean
    /** Turn off when the search box lives somewhere else on the page. */
    showSearch?: boolean
}): JSX.Element {
    const { search, hideFeatureFlagInsights, favorited, tags, insightType, createdBy, order } = filters
    const quickFilterSet = new Set(quickFilters)
    const hasInsightTypeSelection = !!insightType && insightType !== 'All types'

    return (
        <div className={cn('flex justify-between gap-2 items-center flex-wrap')}>
            {showSearch && (
                <LemonInput
                    type="search"
                    placeholder="Search for insights"
                    onChange={(value) => setFilters({ search: value })}
                    value={search || ''}
                    autoFocus
                    data-attr="insight-dashboard-modal-search"
                />
            )}
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
                        <TagSelect
                            value={tags || []}
                            onChange={(tags) => {
                                setFilters({ tags: tags.length > 0 ? tags : [] })
                                posthog.capture('saved insights filtered', { filter_type: 'tags', value: tags })
                            }}
                        >
                            {(selectedTags) => (
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    active={selectedTags.length > 0}
                                    status={borderless && selectedTags.length === 0 ? 'alt' : 'default'}
                                >
                                    {selectedTags.length > 0 ? `Tags (${selectedTags.length})` : 'Tags'}
                                </LemonButton>
                            )}
                        </TagSelect>
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
                    {quickFilterSet.has('featureFlags') && (
                        <FeatureFlagInsightsToggle
                            hideFeatureFlagInsights={hideFeatureFlagInsights ?? undefined}
                            onToggle={(checked) => setFilters({ hideFeatureFlagInsights: checked })}
                        />
                    )}
                    {quickFilterSet.has('sort') && (
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            size="small"
                            icon={<IconSort />}
                            options={INSIGHT_SORT_OPTIONS}
                            value={order}
                            onChange={(value) => {
                                setFilters({ order: value })
                                posthog.capture('saved insights filtered', { filter_type: 'order', value })
                            }}
                            renderButtonContent={(option) => <>Sort: {option?.label ?? 'Custom'}</>}
                        />
                    )}
                </div>
            )}
        </div>
    )
}

const FeatureFlagInsightsToggle = ({
    hideFeatureFlagInsights,
    onToggle,
}: {
    hideFeatureFlagInsights?: boolean
    onToggle: (checked: boolean) => void
}): JSX.Element => {
    return (
        <Tooltip
            title={
                <div>
                    <p>
                        PostHog automatically creates insights by default for feature flags to help you understand their
                        performance.
                    </p>
                    <p className="mb-0">
                        Use this toggle to hide these auto-generated insights from your insights list.
                    </p>
                </div>
            }
            placement="top"
        >
            <LemonButton
                icon={<IconFlag />}
                onClick={() => onToggle(!hideFeatureFlagInsights)}
                type="tertiary"
                size="small"
            >
                Hide feature flag insights: <LemonSwitch checked={hideFeatureFlagInsights || false} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
