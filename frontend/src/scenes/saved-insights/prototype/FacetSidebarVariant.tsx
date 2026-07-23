/**
 * PROTOTYPE variant B — "Faceted sidebar".
 *
 * Every filter is permanently visible in a left rail, file-browser style: scope
 * (all / mine / favorites), insight type, tags, creator. No tabs, no dropdown row —
 * the current filter state is always on screen.
 */
import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconHeart, IconList, IconPerson } from '@posthog/icons'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { TagSelect } from 'lib/components/TagSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { SavedInsightsTabs } from '~/types'

import { SavedInsightListItem, savedInsightsLogic } from '../savedInsightsLogic'
import { CLEARED_FILTERS, PROTOTYPE_TYPE_OPTIONS, PrototypeEmptyState, PrototypeTypeIcon } from './shared'

function FacetSection({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <h5 className="text-xs font-semibold uppercase text-secondary mb-0 px-2">{title}</h5>
            {children}
        </div>
    )
}

export function FacetSidebarVariant(): JSX.Element {
    const { insights, insightsLoading, filters, sorting, pagination, usingFilters } = useValues(savedInsightsLogic)
    const { setSavedInsightsFilters: setFilters } = useActions(savedInsightsLogic)
    const summarizeInsight = useSummarizeInsight()

    const scope: 'all' | 'mine' | 'favorites' = filters.favorited
        ? 'favorites'
        : filters.tab === SavedInsightsTabs.Yours
          ? 'mine'
          : 'all'
    const activeType = filters.insightType && filters.insightType !== 'All types' ? filters.insightType : null
    const createdByIds = filters.createdBy !== 'All users' ? filters.createdBy : []

    const columns: LemonTableColumns<SavedInsightListItem> = [
        {
            key: 'icon',
            width: 32,
            render: (_, insight) => <PrototypeTypeIcon insight={insight} className="text-secondary text-2xl" />,
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: (name, insight) => (
                <LemonTableLink
                    to={urls.insightView(insight.short_id)}
                    title={(name as string) || <i>{summarizeInsight(insight.query)}</i>}
                    description={insight.description}
                />
            ),
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: (_, insight) =>
                insight.created_by ? <ProfilePicture user={insight.created_by} size="md" showName /> : null,
        },
        {
            title: 'Last modified',
            dataIndex: 'last_modified_at',
            sorter: true,
            defaultSortOrder: -1,
            render: (lastModifiedAt) => (
                <div className="whitespace-nowrap">
                    {lastModifiedAt ? <TZLabel time={lastModifiedAt as string} /> : null}
                </div>
            ),
        },
    ]

    return (
        <div className="flex gap-4 items-start">
            <aside className="w-56 shrink-0 flex flex-col gap-4">
                <FacetSection title="Show">
                    <LemonButton
                        size="small"
                        fullWidth
                        active={scope === 'all'}
                        icon={<IconList />}
                        onClick={() => setFilters({ tab: SavedInsightsTabs.All, favorited: false })}
                    >
                        All insights
                    </LemonButton>
                    <LemonButton
                        size="small"
                        fullWidth
                        active={scope === 'mine'}
                        icon={<IconPerson />}
                        onClick={() => setFilters({ tab: SavedInsightsTabs.Yours, favorited: false })}
                    >
                        My insights
                    </LemonButton>
                    <LemonButton
                        size="small"
                        fullWidth
                        active={scope === 'favorites'}
                        icon={<IconHeart />}
                        onClick={() => setFilters({ tab: SavedInsightsTabs.All, favorited: true })}
                    >
                        Favorites
                    </LemonButton>
                </FacetSection>
                <FacetSection title="Type">
                    <LemonButton
                        size="small"
                        fullWidth
                        active={!activeType}
                        onClick={() => setFilters({ insightType: 'All types' })}
                    >
                        All types
                    </LemonButton>
                    {PROTOTYPE_TYPE_OPTIONS.map(({ value, label, Icon }) => (
                        <LemonButton
                            key={value}
                            size="small"
                            fullWidth
                            active={activeType === value}
                            icon={<Icon />}
                            onClick={() =>
                                setFilters({ insightType: activeType === value ? 'All types' : value })
                            }
                        >
                            {label}
                        </LemonButton>
                    ))}
                </FacetSection>
                <FacetSection title="More">
                    <TagSelect
                        value={filters.tags ?? []}
                        onChange={(tags) => setFilters({ tags: tags.length > 0 ? tags : undefined })}
                    >
                        {(selectedTags) => (
                            <LemonButton size="small" fullWidth type="secondary" active={selectedTags.length > 0}>
                                {selectedTags.length > 0 ? `Tags (${selectedTags.length})` : 'Tags'}
                            </LemonButton>
                        )}
                    </TagSelect>
                    <MemberSelectMultiplePopover
                        value={createdByIds}
                        onChange={(ids) => setFilters({ createdBy: ids.length > 0 ? ids : 'All users' })}
                    />
                    <div className="px-2 pt-1">
                        <LemonCheckbox
                            label="Hide feature flag insights"
                            checked={!!filters.hideFeatureFlagInsights}
                            onChange={(checked) => setFilters({ hideFeatureFlagInsights: checked })}
                        />
                    </div>
                </FacetSection>
                {usingFilters && (
                    <LemonButton size="small" type="tertiary" onClick={() => setFilters(CLEARED_FILTERS)}>
                        Reset filters
                    </LemonButton>
                )}
            </aside>
            <div className="flex-1 min-w-0 flex flex-col gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search insights…"
                    value={filters.search || ''}
                    onChange={(search) => setFilters({ search })}
                    fullWidth
                    autoFocus
                />
                <LemonTable
                    loading={insightsLoading}
                    columns={columns}
                    dataSource={insights.results}
                    pagination={pagination}
                    noSortingCancellation
                    sorting={sorting}
                    onSort={(newSorting) =>
                        setFilters({
                            order: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                        })
                    }
                    rowKey="id"
                    loadingSkeletonRows={15}
                    nouns={['insight', 'insights']}
                    emptyState={!insightsLoading && insights.count < 1 ? <PrototypeEmptyState /> : undefined}
                />
            </div>
        </div>
    )
}
