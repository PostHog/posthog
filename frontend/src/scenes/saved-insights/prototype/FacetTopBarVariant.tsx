/**
 * PROTOTYPE variant B — "Faceted top bar".
 *
 * Every filter lives in labeled rows above the list: scope (all / mine / favorites),
 * insight type, tags, creator. No tabs — the active filter state is always on screen.
 */
import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconHeart, IconList, IconPerson } from '@posthog/icons'

import { MemberSelectMultiplePopover } from 'lib/components/MemberSelectMultiplePopover'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
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

function FacetRow({ title, children }: { title: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex items-center gap-1 flex-wrap">
            <span className="text-xs font-semibold uppercase text-secondary w-12 shrink-0">{title}</span>
            {children}
        </div>
    )
}

export function FacetTopBarVariant(): JSX.Element {
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
            title: 'Tags',
            key: 'tags',
            render: (_, insight) => <ObjectTags tags={[...(insight.tags ?? [])].sort()} staticOnly />,
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
        <div className="flex flex-col gap-2">
            <FacetRow title="Show">
                <LemonButton
                    size="small"
                    type={scope === 'all' ? 'primary' : 'secondary'}
                    icon={<IconList />}
                    onClick={() => setFilters({ tab: SavedInsightsTabs.All, favorited: false })}
                >
                    All insights
                </LemonButton>
                <LemonButton
                    size="small"
                    type={scope === 'mine' ? 'primary' : 'secondary'}
                    icon={<IconPerson />}
                    onClick={() => setFilters({ tab: SavedInsightsTabs.Yours, favorited: false })}
                >
                    My insights
                </LemonButton>
                <LemonButton
                    size="small"
                    type={scope === 'favorites' ? 'primary' : 'secondary'}
                    icon={<IconHeart />}
                    onClick={() => setFilters({ tab: SavedInsightsTabs.All, favorited: true })}
                >
                    Favorites
                </LemonButton>
            </FacetRow>
            <FacetRow title="Type">
                <LemonButton
                    size="small"
                    type={!activeType ? 'primary' : 'secondary'}
                    onClick={() => setFilters({ insightType: 'All types' })}
                >
                    All types
                </LemonButton>
                {PROTOTYPE_TYPE_OPTIONS.map(({ value, label, Icon }) => (
                    <LemonButton
                        key={value}
                        size="small"
                        type={activeType === value ? 'primary' : 'secondary'}
                        icon={<Icon />}
                        onClick={() => setFilters({ insightType: activeType === value ? 'All types' : value })}
                    >
                        {label}
                    </LemonButton>
                ))}
            </FacetRow>
            <FacetRow title="More">
                <TagSelect
                    value={filters.tags ?? []}
                    onChange={(tags) => setFilters({ tags: tags.length > 0 ? tags : undefined })}
                >
                    {(selectedTags) => (
                        <LemonButton size="small" type="secondary" active={selectedTags.length > 0}>
                            {selectedTags.length > 0 ? `Tags (${selectedTags.length})` : 'Tags'}
                        </LemonButton>
                    )}
                </TagSelect>
                <MemberSelectMultiplePopover
                    value={createdByIds}
                    onChange={(ids) => setFilters({ createdBy: ids.length > 0 ? ids : 'All users' })}
                />
                <LemonCheckbox
                    label="Hide feature flag insights"
                    checked={!!filters.hideFeatureFlagInsights}
                    onChange={(checked) => setFilters({ hideFeatureFlagInsights: checked })}
                />
                {usingFilters && (
                    <LemonButton
                        size="small"
                        type="tertiary"
                        className="ml-auto"
                        onClick={() => setFilters(CLEARED_FILTERS)}
                    >
                        Reset filters
                    </LemonButton>
                )}
            </FacetRow>
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
                        order: newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : undefined,
                    })
                }
                rowKey="id"
                loadingSkeletonRows={15}
                nouns={['insight', 'insights']}
                emptyState={!insightsLoading && insights.count < 1 ? <PrototypeEmptyState /> : undefined}
            />
        </div>
    )
}
