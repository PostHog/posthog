import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonSkeleton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    CohortCalculationHistoryRecord,
    cohortCalculationHistorySceneLogic,
} from './cohortCalculationHistorySceneLogic'

const RESOURCE_TYPE = 'cohort'

export const scene: SceneExport<CohortCalculationHistoryProps> = {
    component: CohortCalculationHistory,
    logic: cohortCalculationHistorySceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id }),
}

interface CohortCalculationHistoryProps {
    id: string
}

export function CohortCalculationHistory(props: CohortCalculationHistoryProps): JSX.Element {
    const cohortId = props.id && props.id !== 'new' ? parseInt(props.id) : 0

    const logic = cohortCalculationHistorySceneLogic({ cohortId })
    const {
        calculationHistory,
        calculationHistoryResponseLoading,
        cohort,
        cohortMissing,
        totalRecords,
        page,
        limit,
        hasCalculationHistoryAccess,
    } = useValues(logic)
    const { setPage } = useActions(logic)

    if (!cohortId || cohortId <= 0) {
        return <div>Invalid cohort ID: {cohortId}. Please ensure you're visiting a valid cohort.</div>
    }

    if (!hasCalculationHistoryAccess) {
        return <NotFound object="page" />
    }

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }

    const columns: LemonTableColumns<CohortCalculationHistoryRecord> = [
        {
            title: 'Started',
            dataIndex: 'started_at',
            render: (_, record) => <TZLabel time={record.started_at} />,
            sorter: true,
        },
        {
            title: 'Count',
            dataIndex: 'count',
            render: (count) => (count !== null ? count.toLocaleString() : '-'),
        },
        {
            title: 'Queries',
            render: (_, record) => record.queries?.length || 0,
        },
        {
            title: 'Total Query Time',
            render: (_, record) => {
                const totalMs = record.total_query_ms
                return totalMs ? `${(totalMs / 1000).toFixed(2)}s` : '-'
            },
        },
        {
            title: 'Max Memory Usage',
            render: (_, record) => {
                const queries = record.queries || []
                if (queries.length === 0) {
                    return '-'
                }

                const maxMb = Math.max(...queries.map((q) => q.memory_mb || 0))
                return maxMb > 0 ? `${maxMb.toFixed(1)} MB` : '-'
            },
        },
        {
            title: 'Rows Read',
            render: (_, record) => {
                const totalRows = record.total_read_rows
                return totalRows ? totalRows.toLocaleString() : '-'
            },
        },
        {
            title: 'Status',
            render: (_, record) => {
                if (record.error) {
                    return <span className="text-danger">Error</span>
                }
                if (!record.finished_at) {
                    return <span className="text-warning">In Progress</span>
                }
                return <span className="text-success">Completed</span>
            },
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={`Calculation History - ${cohort?.name || 'Cohort'}`}
                description="History of all calculations performed for this cohort, including performance metrics and timing information."
                resourceType={{
                    to: urls.cohorts(),
                    type: RESOURCE_TYPE,
                    forceIcon: <IconClock />,
                }}
                forceBackTo={{
                    key: cohortId,
                    name: cohort?.name || 'Cohort',
                    path: urls.cohort(cohortId),
                }}
            />

            {calculationHistoryResponseLoading ? (
                <div className="space-y-4">
                    <LemonSkeleton className="h-8" />
                    <LemonSkeleton className="h-8" />
                    <LemonSkeleton className="h-8" />
                    <LemonSkeleton className="h-8" />
                </div>
            ) : (
                <LemonTable
                    columns={columns}
                    dataSource={calculationHistory}
                    pagination={{
                        controlled: true,
                        currentPage: page,
                        pageSize: limit,
                        entryCount: totalRecords,
                        onForward: () => setPage(page + 1),
                        onBackward: () => setPage(page - 1),
                    }}
                    expandable={{
                        expandedRowRender: (record) => (
                            <div className="p-4 bg-bg-light">
                                {record.error && (
                                    <div className="mb-4">
                                        <h4 className="text-danger">Error</h4>
                                        <pre className="text-xs bg-danger-highlight p-2 rounded overflow-auto">
                                            {record.error}
                                        </pre>
                                    </div>
                                )}

                                {record.queries && record.queries.length > 0 && (
                                    <div>
                                        <h4>Query Details</h4>
                                        <div className="space-y-2">
                                            {record.queries.map((query, index: number) => (
                                                <div key={index} className="border border-border rounded p-2">
                                                    <div className="grid grid-cols-4 gap-4 text-xs">
                                                        <div>
                                                            <strong>Query Time:</strong> {query.query_ms}ms
                                                        </div>
                                                        <div>
                                                            <strong>Memory:</strong> {query.memory_mb?.toFixed(1)} MB
                                                        </div>
                                                        <div>
                                                            <strong>Rows Read:</strong>{' '}
                                                            {query.read_rows?.toLocaleString()}
                                                        </div>
                                                        <div>
                                                            <strong>Rows Written:</strong>{' '}
                                                            {query.written_rows?.toLocaleString()}
                                                        </div>
                                                    </div>
                                                    {query.query && (
                                                        <details className="mt-2">
                                                            <summary className="cursor-pointer text-primary">
                                                                Show Query
                                                            </summary>
                                                            <pre className="mt-2 text-xs bg-bg-3000 p-2 rounded overflow-auto">
                                                                {query.query}
                                                            </pre>
                                                        </details>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {record.filters && (
                                    <div className="mt-4">
                                        <h4>Filters Used</h4>
                                        <pre className="text-xs bg-bg-3000 p-2 rounded overflow-auto">
                                            {JSON.stringify(record.filters, null, 2)}
                                        </pre>
                                    </div>
                                )}
                            </div>
                        ),
                        rowExpandable: (record) =>
                            !!(record.error || (record.queries && record.queries.length > 0) || record.filters),
                    }}
                />
            )}
        </SceneContent>
    )
}
