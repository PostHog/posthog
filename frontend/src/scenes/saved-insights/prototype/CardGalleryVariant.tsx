/**
 * PROTOTYPE variant C — "Quick pills + card gallery".
 *
 * Built for browsing: one-click type and scope pills instead of dropdowns, and a
 * visual card grid instead of a metadata-heavy table. Sort lives in a single select.
 */
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconHeartFilled } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { SavedInsightsTabs } from '~/types'

import { SavedInsightListItem, savedInsightsLogic } from '../savedInsightsLogic'
import { PROTOTYPE_TYPE_OPTIONS, PrototypeEmptyState, PrototypeTypeIcon, insightTypeMetadata } from './shared'

const GRID_STYLE = { gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }

export function CardGalleryVariant(): JSX.Element {
    const { insights, insightsLoading, filters, pagination } = useValues(savedInsightsLogic)
    const { setSavedInsightsFilters: setFilters } = useActions(savedInsightsLogic)
    const { push } = useActions(router)
    const summarizeInsight = useSummarizeInsight()
    const paginationState = usePagination(insights.results, pagination)

    const activeType = filters.insightType && filters.insightType !== 'All types' ? filters.insightType : null

    return (
        <div className="flex flex-col gap-3">
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
                <LemonSelect
                    size="small"
                    dropdownMatchSelectWidth={false}
                    value={filters.order}
                    onChange={(order) => setFilters({ order: order ?? undefined })}
                    options={[
                        { value: '-last_modified_at', label: 'Last modified' },
                        { value: '-created_at', label: 'Newest' },
                        { value: '-last_viewed_at', label: 'Recently viewed' },
                    ]}
                />
            </div>
            <div className="flex flex-wrap gap-1 items-center">
                <LemonButton
                    size="xsmall"
                    type={!activeType ? 'primary' : 'secondary'}
                    onClick={() => setFilters({ insightType: 'All types' })}
                >
                    All types
                </LemonButton>
                {PROTOTYPE_TYPE_OPTIONS.map(({ value, label, Icon }) => (
                    <LemonButton
                        key={value}
                        size="xsmall"
                        type={activeType === value ? 'primary' : 'secondary'}
                        icon={<Icon />}
                        onClick={() => setFilters({ insightType: activeType === value ? 'All types' : value })}
                    >
                        {label}
                    </LemonButton>
                ))}
                <LemonDivider vertical className="h-4" />
                <LemonButton
                    size="xsmall"
                    type={filters.tab === SavedInsightsTabs.Yours ? 'primary' : 'secondary'}
                    onClick={() =>
                        setFilters({
                            tab:
                                filters.tab === SavedInsightsTabs.Yours
                                    ? SavedInsightsTabs.All
                                    : SavedInsightsTabs.Yours,
                        })
                    }
                >
                    Mine
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type={filters.favorited ? 'primary' : 'secondary'}
                    onClick={() => setFilters({ favorited: !filters.favorited })}
                >
                    Favorites
                </LemonButton>
            </div>
            {insightsLoading ? (
                <div className="grid gap-3" style={GRID_STYLE}>
                    {Array.from({ length: 9 }, (_, index) => (
                        <LemonSkeleton key={index} className="h-36 rounded" />
                    ))}
                </div>
            ) : insights.results.length === 0 ? (
                <PrototypeEmptyState />
            ) : (
                <div className="grid gap-3" style={GRID_STYLE}>
                    {insights.results.map((insight) => (
                        <InsightCard
                            key={insight.short_id}
                            insight={insight}
                            summary={summarizeInsight(insight.query)}
                            onOpen={() => push(urls.insightView(insight.short_id))}
                        />
                    ))}
                </div>
            )}
            <div className="flex justify-end">
                <PaginationControl {...paginationState} nouns={['insight', 'insights']} />
            </div>
        </div>
    )
}

function InsightCard({
    insight,
    summary,
    onOpen,
}: {
    insight: SavedInsightListItem
    summary: string
    onOpen: () => void
}): JSX.Element {
    const typeName = insightTypeMetadata(insight)?.name

    return (
        <LemonCard className="p-4 flex flex-col gap-2" onClick={onOpen}>
            <div className="flex items-center gap-2">
                <PrototypeTypeIcon insight={insight} className="text-secondary text-xl" />
                {typeName && <span className="text-xs text-secondary">{typeName}</span>}
                {insight.favorited && <IconHeartFilled className="text-danger ml-auto" />}
            </div>
            <div className="font-semibold leading-tight line-clamp-2">{insight.name || <i>{summary}</i>}</div>
            {insight.description && (
                <div className="text-xs text-secondary line-clamp-2">{insight.description}</div>
            )}
            <div className="flex items-center gap-2 mt-auto pt-1">
                {insight.created_by && <ProfilePicture user={insight.created_by} size="sm" />}
                <span className="text-xs text-secondary">
                    {insight.last_modified_at && <TZLabel time={insight.last_modified_at} />}
                </span>
                <div className="flex gap-1 ml-auto overflow-hidden">
                    {(insight.tags ?? []).slice(0, 2).map((tag) => (
                        <LemonTag key={tag} size="small">
                            {tag}
                        </LemonTag>
                    ))}
                </div>
            </div>
        </LemonCard>
    )
}
