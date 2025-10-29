import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { organizationLogic } from 'scenes/organizationLogic'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { INSIGHTS_PER_PAGE, addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

import { InsightIcon } from '../../saved-insights/SavedInsights'
import { notebookLogic } from '../Notebook/notebookLogic'

// TODO: Refactor this component to reuse code from AddSavedInsightsToDashboard.
export function AddSavedInsightsToNotebook(): JSX.Element {
    const { modalPage, insights, count, insightsLoading, filters, sorting } = useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters } = useActions(addSavedInsightsModalLogic)
    const { addSavedInsightsToNotebook } = useActions(notebookLogic)

    const { hasTagging } = useValues(organizationLogic)

    // TODO: Move this to logic
    const [addingInsights, setAddingInsights] = useState<Record<number, boolean>>({})

    const summarizeInsight = useSummarizeInsight()

    const handleAddInsight = async (insight: QueryBasedInsightModel): Promise<void> => {
        setAddingInsights((prev) => ({ ...prev, [insight.id]: true }))

        try {
            addSavedInsightsToNotebook([insight.short_id])
        } catch (error) {
            console.error('Error adding insight to notebook:', error)
            lemonToast.error('Failed to add insight to notebook')
        } finally {
            setAddingInsights((prev) => ({ ...prev, [insight.id]: false }))
        }
    }

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            width: 0,
            render: function Render(_, insight) {
                const isAdding = addingInsights[insight.id]
                return (
                    <LemonButton
                        type="secondary"
                        size="small"
                        fullWidth
                        disabled={isAdding}
                        onClick={(e) => {
                            e.preventDefault()
                            if (!isAdding) {
                                void handleAddInsight(insight)
                            }
                        }}
                    >
                        {isAdding ? <Spinner textColored /> : <IconPlusSmall />}
                    </LemonButton>
                )
            },
        },
        {
            key: 'id',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} className="text-secondary text-2xl" />
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <>
                        <div className="flex flex-col gap-1 min-w-0">
                            <div className="flex min-w-0">
                                <Link
                                    to={urls.insightView(insight.short_id)}
                                    target="_blank"
                                    title={name || summarizeInsight(insight.query)}
                                    className="w-0 flex-1 min-w-0"
                                >
                                    <span className="block truncate">
                                        {name || <i>{summarizeInsight(insight.query)}</i>}
                                    </span>
                                </Link>
                            </div>
                            {hasTagging && insight.tags && insight.tags.length > 0 && (
                                <ObjectTags
                                    tags={insight.tags}
                                    saving={false}
                                    className="insight-metadata"
                                    staticOnly
                                />
                            )}
                        </div>
                    </>
                )
            },
        },
        createdByColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
        createdAtColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap text-right">
                        <TZLabel time={last_modified_at} />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="space-y-4 insight-list">
            <SavedInsightsFilters filters={filters} setFilters={setModalFilters} />
            <LemonDivider />
            <div>
                {!insights.results.length ? (
                    insightsLoading ? (
                        <div className="flex justify-center">
                            <Spinner className="text-4xl" />
                        </div>
                    ) : (
                        <SavedInsightsEmptyState filters={filters} usingFilters />
                    )
                ) : (
                    <div className="space-y-2">
                        <LemonTable
                            dataSource={insights.results}
                            columns={columns}
                            size="small"
                            loading={insightsLoading}
                            pagination={{
                                controlled: true,
                                pageSize: INSIGHTS_PER_PAGE,
                                currentPage: modalPage,
                                entryCount: count,
                                onForward: () => {
                                    setModalPage(modalPage + 1)
                                },
                                onBackward: () => {
                                    setModalPage(modalPage - 1)
                                },
                            }}
                            data-attr="insights-table"
                            nouns={['insight', 'insights']}
                            defaultSorting={sorting}
                            onSort={(newSorting) => setModalFilters({ order: newSorting })}
                        />
                    </div>
                )}
            </div>
        </div>
    )
}
