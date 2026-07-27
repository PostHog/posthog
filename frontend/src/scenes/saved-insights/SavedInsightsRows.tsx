import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { urls } from 'scenes/urls'

import { isDraftInsightRow } from './draftInsight'
import { DraftInsightMoreMenu, DraftInsightNameCell } from './DraftInsightRow'
import { InsightFavoriteButton, InsightMoreMenu, useInsightsBulkSelection } from './InsightActions'
import { insightTypeMetadata } from './insightTypesMetadata'
import { QuickFilterKind, SavedInsightsFilters } from './SavedInsightsFilters'
import { SavedInsightListItem, savedInsightsLogic } from './savedInsightsLogic'

/** Muted one-liner under the name: type, who made it, and when things last happened to it. */
function InsightRowMeta({ insight, typeName }: { insight: SavedInsightListItem; typeName?: string }): JSX.Element {
    const parts: JSX.Element[] = []

    if (typeName) {
        parts.push(<span key="type">{typeName}</span>)
    }
    if (insight.created_at) {
        parts.push(
            <div key="created" className="flex items-center gap-1">
                created <TZLabel time={insight.created_at} showPopover={false} />
                {insight.created_by && (
                    <>
                        by <ProfilePicture user={insight.created_by} size="xs" showName />
                    </>
                )}
            </div>
        )
    }
    if (insight.last_modified_at) {
        parts.push(
            <span key="modified">
                edited <TZLabel time={insight.last_modified_at} showPopover={false} />
            </span>
        )
    }
    parts.push(
        insight.last_viewed_at ? (
            <span key="viewed">
                viewed <TZLabel time={insight.last_viewed_at} showPopover={false} />
            </span>
        ) : (
            <span key="viewed">never viewed</span>
        )
    )

    return (
        <div className="flex items-center flex-wrap gap-x-1.5 text-xs text-secondary">
            {parts.map((part, index) => (
                <Fragment key={part.key}>
                    {index > 0 && <span className="text-tertiary">·</span>}
                    {part}
                </Fragment>
            ))}
        </div>
    )
}

function InsightRow({ insight }: { insight: SavedInsightListItem }): JSX.Element {
    const summarizeInsight = useSummarizeInsight()
    const typeMetadata = insightTypeMetadata(insight)
    const Icon = typeMetadata?.icon

    if (isDraftInsightRow(insight)) {
        return (
            <div className="flex items-center gap-2">
                {Icon && <Icon className="text-secondary text-xl shrink-0" />}
                <div className="flex-1 min-w-0">
                    <DraftInsightNameCell item={insight} />
                </div>
                <DraftInsightMoreMenu item={insight} />
            </div>
        )
    }

    return (
        <div className="flex items-start gap-2">
            {Icon && <Icon className="text-secondary text-xl shrink-0 mt-0.5" />}
            <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                <div className="flex items-center flex-wrap gap-1.5">
                    <Link to={urls.insightView(insight.short_id)} className="text-sm font-semibold">
                        {insight.name || <i>{summarizeInsight(insight.query)}</i>}
                    </Link>
                    {insight.tags && insight.tags.length > 0 && (
                        <ObjectTags tags={[...insight.tags].sort()} staticOnly />
                    )}
                    {insight.search_match_type === 'similar' && (
                        <Tooltip title="Not an exact match for your search, but a close one">
                            <LemonTag type="muted" size="small">
                                similar
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>
                {insight.description && <div className="text-xs text-secondary truncate">{insight.description}</div>}
                <InsightRowMeta insight={insight} typeName={typeMetadata?.name} />
            </div>
            <div className="flex items-center gap-0.5 shrink-0">
                <InsightFavoriteButton insight={insight} />
                <InsightMoreMenu insight={insight} />
            </div>
        </div>
    )
}

/**
 * Insights as a plain list of rows instead of a grid of columns — each insight carries its own
 * metadata inline, and the filters live in the list header where the column titles used to be.
 */
export function SavedInsightsRows({ quickFilters }: { quickFilters?: QuickFilterKind[] }): JSX.Element {
    const { insights, insightsLoading, filters, pagination, usingFilters, draftInsightRow, count } =
        useValues(savedInsightsLogic)
    const { setSavedInsightsFilters } = useActions(savedInsightsLogic)
    const bulkSelection = useInsightsBulkSelection()

    const columns: LemonTableColumns<SavedInsightListItem> = [
        {
            key: 'insight',
            title: (
                <div className="flex items-center justify-between flex-wrap gap-2 w-full font-medium">
                    <span className="text-secondary">
                        {insightsLoading && count === 0 ? '' : `${count} ${count === 1 ? 'insight' : 'insights'}`}
                    </span>
                    <SavedInsightsFilters
                        filters={filters}
                        setFilters={setSavedInsightsFilters}
                        quickFilters={quickFilters}
                        showSearch={false}
                        borderless
                    />
                </div>
            ),
            render: function renderInsightRow(_, insight) {
                return <InsightRow insight={insight} />
            },
        },
    ]

    return (
        <LemonTable
            className="SavedInsightsRows"
            loading={insightsLoading}
            columns={columns}
            dataSource={draftInsightRow ? [draftInsightRow, ...insights.results] : insights.results}
            rowClassName={(record) => (isDraftInsightRow(record) ? 'bg-warning-highlight' : null)}
            pagination={pagination}
            rowKey="id"
            uppercaseHeader={false}
            // Sorting is driven by the header's sort dropdown, so keep LemonTable out of the URL
            useURLForSorting={false}
            loadingSkeletonRows={8}
            nouns={['insight', 'insights']}
            emptyState={
                !insightsLoading && insights.count < 1 ? (
                    <div className="py-8">
                        <SavedInsightsEmptyState filters={filters} usingFilters={usingFilters} />
                    </div>
                ) : undefined
            }
            bulkSelection={bulkSelection}
        />
    )
}
