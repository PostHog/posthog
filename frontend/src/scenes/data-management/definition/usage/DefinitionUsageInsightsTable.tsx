import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'
import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema/schema-general'
import { isNodeWithSource } from '~/queries/utils'
import { InsightShortId } from '~/types'

import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'

import {
    DEFINITION_INSIGHTS_PER_PAGE,
    DefinitionInsightsLogicProps,
    dashboardIdsOf,
    definitionInsightsLogic,
} from './definitionInsightsLogic'

function insightTypeName(query: Node | null): string | undefined {
    if (!query) {
        return undefined
    }
    const kind = isNodeWithSource(query) ? query.source.kind : query.kind
    return QUERY_TYPES_METADATA[kind]?.name
}

export function DefinitionUsageInsightsTable({
    logicProps,
}: {
    logicProps: DefinitionInsightsLogicProps
}): JSX.Element {
    const logic = definitionInsightsLogic(logicProps)
    const { insights, insightsLoading, insightsFailed, search, page, sorting } = useValues(logic)
    const { setSearch, setOrder, setPage, reportInsightOpened } = useActions(logic)
    const summarizeInsight = useSummarizeInsight()

    const columns: LemonTableColumns<InsightApi> = [
        {
            title: 'Name',
            key: 'name',
            render: function renderName(_, insight) {
                const query = (insight.query ?? null) as Node | null
                return (
                    <LemonTableLink
                        to={urls.insightView(insight.short_id as InsightShortId)}
                        onClick={() => reportInsightOpened()}
                        title={insight.name || insight.derived_name || <i>{summarizeInsight(query)}</i>}
                        description={insightTypeName(query)}
                    />
                )
            },
        },
        {
            title: 'Dashboards',
            key: 'dashboards',
            align: 'right',
            render: function renderDashboards(_, insight) {
                return dashboardIdsOf(insight).length.toLocaleString()
            },
        },
        {
            title: 'Last viewed',
            key: 'last_viewed_at',
            sorter: true,
            render: function renderLastViewed(_, insight) {
                return (
                    <div className="whitespace-nowrap">
                        {insight.last_viewed_at ? (
                            <TZLabel time={insight.last_viewed_at} />
                        ) : (
                            <span className="text-secondary">Never</span>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Created by',
            key: 'created_by',
            render: function renderCreatedBy(_, insight) {
                // The generated type says non-null, but the creator foreign key is SET_NULL, so system-created
                // insights and insights of deleted users arrive with `created_by: null`.
                const createdBy: InsightApi['created_by'] | null = insight.created_by
                if (!createdBy) {
                    return <span className="text-secondary">—</span>
                }
                const { first_name, last_name, email } = createdBy
                return <ProfilePicture user={{ first_name, last_name, email }} size="md" showName />
            },
        },
        {
            title: 'Last modified',
            key: 'last_modified_at',
            sorter: true,
            render: function renderLastModified(_, insight) {
                return (
                    <div className="whitespace-nowrap">
                        <TZLabel time={insight.last_modified_at} />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <LemonInput
                type="search"
                placeholder="Search saved insights"
                value={search}
                onChange={setSearch}
                className="max-w-80"
                data-attr="definition-usage-insights-search"
            />
            <LemonTable
                columns={columns}
                dataSource={insightsFailed ? [] : (insights?.results ?? [])}
                loading={insightsLoading}
                loadingSkeletonRows={DEFINITION_INSIGHTS_PER_PAGE}
                rowKey="id"
                data-attr="definition-usage-insights-table"
                nouns={['insight', 'insights']}
                pagination={{
                    controlled: true,
                    currentPage: page,
                    entryCount: insights?.count ?? 0,
                    pageSize: DEFINITION_INSIGHTS_PER_PAGE,
                    onForward: insights?.next ? () => setPage(page + 1) : undefined,
                    onBackward: insights?.previous ? () => setPage(page - 1) : undefined,
                }}
                sorting={sorting}
                onSort={(newSorting) =>
                    setOrder(newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : null)
                }
                useURLForSorting={false}
                emptyState={
                    insightsFailed
                        ? "Couldn't load saved insights. Refresh the page to try again."
                        : search
                          ? 'No saved insights match this search'
                          : `No saved insights use this ${logicProps.definitionType}`
                }
            />
        </div>
    )
}
