/**
 * PROTOTYPE variant A — "Filter by example".
 *
 * One search box and one compact "Filters" panel instead of the scattered dropdown row.
 * The list itself is the main filter surface: click a tag or a creator to filter by it.
 * Every active filter shows as a removable chip under the search box.
 */
import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { InsightType, SavedInsightsTabs } from '~/types'

import { INSIGHT_TYPES_METADATA } from '../insightTypesMetadata'
import { SavedInsightListItem, savedInsightsLogic } from '../savedInsightsLogic'
import { CLEARED_FILTERS, PROTOTYPE_TYPE_OPTIONS, PrototypeEmptyState, PrototypeTypeIcon } from './shared'

interface FilterChip {
    key: string
    label: string
    onRemove: () => void
}

export function FilterByExampleVariant(): JSX.Element {
    const { insights, insightsLoading, filters, sorting, pagination } = useValues(savedInsightsLogic)
    const { setSavedInsightsFilters: setFilters } = useActions(savedInsightsLogic)
    const summarizeInsight = useSummarizeInsight()

    const activeTags = filters.tags ?? []
    const createdByIds = filters.createdBy !== 'All users' ? filters.createdBy : []

    const toggleTag = (tag: string): void => {
        setFilters({ tags: activeTags.includes(tag) ? activeTags.filter((t) => t !== tag) : [...activeTags, tag] })
    }

    const creatorName = (id: number): string => {
        const match = insights.results.find((i) => i.created_by?.id === id)?.created_by
        return match ? match.first_name || match.email : `member #${id}`
    }

    const chips: FilterChip[] = [
        ...(filters.insightType && filters.insightType !== 'All types'
            ? [
                  {
                      key: 'type',
                      label: `Type: ${INSIGHT_TYPES_METADATA[filters.insightType as InsightType]?.name ?? filters.insightType}`,
                      onRemove: () => setFilters({ insightType: 'All types' }),
                  },
              ]
            : []),
        ...(filters.tab === SavedInsightsTabs.Yours
            ? [
                  {
                      key: 'mine',
                      label: 'Only my insights',
                      onRemove: () => setFilters({ tab: SavedInsightsTabs.All }),
                  },
              ]
            : []),
        ...(filters.favorited
            ? [{ key: 'favorites', label: 'Only favorites', onRemove: () => setFilters({ favorited: false }) }]
            : []),
        ...(filters.hideFeatureFlagInsights
            ? [
                  {
                      key: 'hide-flags',
                      label: 'Feature flag insights hidden',
                      onRemove: () => setFilters({ hideFeatureFlagInsights: false }),
                  },
              ]
            : []),
        ...activeTags.map((tag) => ({ key: `tag-${tag}`, label: `#${tag}`, onRemove: () => toggleTag(tag) })),
        ...createdByIds.map((id) => ({
            key: `creator-${id}`,
            label: `By ${creatorName(id)}`,
            onRemove: () =>
                setFilters({
                    createdBy: createdByIds.length > 1 ? createdByIds.filter((c) => c !== id) : 'All users',
                }),
        })),
    ]

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
            render: (_, insight) => (
                <div className="flex flex-wrap gap-1">
                    {(insight.tags ?? []).map((tag) => (
                        <LemonTag
                            key={tag}
                            className="cursor-pointer"
                            type={activeTags.includes(tag) ? 'highlight' : 'default'}
                            onClick={() => toggleTag(tag)}
                        >
                            {tag}
                        </LemonTag>
                    ))}
                </div>
            ),
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: (_, insight) =>
                insight.created_by ? (
                    <LemonButton
                        size="xsmall"
                        onClick={() => setFilters({ createdBy: [insight.created_by!.id] })}
                        tooltip="Show only insights by this person"
                    >
                        <ProfilePicture user={insight.created_by} size="md" showName />
                    </LemonButton>
                ) : null,
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
            <div className="flex gap-2 items-center">
                <div className="flex-1">
                    <LemonInput
                        type="search"
                        placeholder="Search insights…"
                        value={filters.search || ''}
                        onChange={(search) => setFilters({ search })}
                        fullWidth
                        autoFocus
                    />
                </div>
                <LemonDropdown closeOnClickInside={false} placement="bottom-end" overlay={<FilterPanel />}>
                    <LemonButton type="secondary" icon={<IconFilter />} active={chips.length > 0}>
                        Filters{chips.length > 0 ? ` (${chips.length})` : ''}
                    </LemonButton>
                </LemonDropdown>
            </div>
            {chips.length > 0 && (
                <div className="flex flex-wrap gap-1 items-center">
                    {chips.map((chip) => (
                        <LemonSnack key={chip.key} onClose={chip.onRemove}>
                            {chip.label}
                        </LemonSnack>
                    ))}
                    <LemonButton size="xsmall" onClick={() => setFilters(CLEARED_FILTERS)}>
                        Clear all
                    </LemonButton>
                </div>
            )}
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
    )
}

function FilterPanel(): JSX.Element {
    const { filters } = useValues(savedInsightsLogic)
    const { setSavedInsightsFilters: setFilters } = useActions(savedInsightsLogic)

    return (
        <div className="flex flex-col gap-3 p-2 w-100 max-w-full">
            <div>
                <LemonLabel>Type</LemonLabel>
                <div className="flex flex-wrap gap-1 mt-1">
                    <LemonButton
                        size="xsmall"
                        type={!filters.insightType || filters.insightType === 'All types' ? 'primary' : 'secondary'}
                        onClick={() => setFilters({ insightType: 'All types' })}
                    >
                        All
                    </LemonButton>
                    {PROTOTYPE_TYPE_OPTIONS.map(({ value, label, Icon }) => (
                        <LemonButton
                            key={value}
                            size="xsmall"
                            type={filters.insightType === value ? 'primary' : 'secondary'}
                            icon={<Icon />}
                            onClick={() => setFilters({ insightType: value })}
                        >
                            {label}
                        </LemonButton>
                    ))}
                </div>
            </div>
            <div>
                <LemonLabel>Show</LemonLabel>
                <div className="flex flex-col gap-2 mt-1">
                    <LemonCheckbox
                        label="Only my insights"
                        checked={filters.tab === SavedInsightsTabs.Yours}
                        onChange={(checked) =>
                            setFilters({ tab: checked ? SavedInsightsTabs.Yours : SavedInsightsTabs.All })
                        }
                    />
                    <LemonCheckbox
                        label="Only favorites"
                        checked={!!filters.favorited}
                        onChange={(checked) => setFilters({ favorited: checked })}
                    />
                    <LemonCheckbox
                        label="Hide feature flag insights"
                        checked={!!filters.hideFeatureFlagInsights}
                        onChange={(checked) => setFilters({ hideFeatureFlagInsights: checked })}
                    />
                </div>
            </div>
            <div className="text-xs text-secondary border-t pt-2">
                Tip: click a tag or creator in the list to filter by it.
            </div>
        </div>
    )
}
