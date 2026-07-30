import { useValues } from 'kea'

import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { DataModelingJob } from '~/types'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

export function NodeDetailDataQuality({ id }: { id: string }): JSX.Element {
    const { savedQuery, hasMaterialization, materializationJobs } = useValues(nodeDetailSceneLogic({ id }))

    const completedRuns = (materializationJobs?.results ?? [])
        .filter((job: DataModelingJob) => job.status === 'Completed')
        .slice()
        .reverse()
    const schemaFields: DatabaseSchemaField[] = Object.values(savedQuery?.columns ?? [])

    return (
        <div className="flex flex-col gap-6 mt-4">
            {hasMaterialization && completedRuns.length > 0 && (
                <div className="flex flex-col gap-2">
                    <h3 className="mb-0">Rows per run</h3>
                    <p className="text-sm text-secondary mb-0">
                        Rows materialized by each completed run. A sudden drop usually means an upstream data problem.
                    </p>
                    <Sparkline
                        className="w-full h-24"
                        data={[
                            {
                                name: 'Rows',
                                values: completedRuns.map((job) => job.rows_materialized),
                                color: 'success',
                            },
                        ]}
                        labels={completedRuns.map((job) => humanFriendlyDetailedTime(job.created_at))}
                        renderTooltipValue={(value) => humanFriendlyNumber(value)}
                    />
                </div>
            )}
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Schema</h3>
                <LemonTable
                    size="small"
                    dataSource={schemaFields}
                    columns={[
                        {
                            title: 'Column',
                            key: 'name',
                            render: (_, field: DatabaseSchemaField) => (
                                <span className="font-mono text-xs">{field.name}</span>
                            ),
                        },
                        {
                            title: 'Type',
                            key: 'type',
                            render: (_, field: DatabaseSchemaField) => field.type,
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, field: DatabaseSchemaField) =>
                                field.schema_valid === false ? (
                                    <LemonTag type="danger">Invalid</LemonTag>
                                ) : (
                                    <LemonTag type="success">Valid</LemonTag>
                                ),
                        },
                    ]}
                    nouns={['column', 'columns']}
                    emptyState="No schema captured yet. Run the query once to capture its columns."
                />
            </div>
        </div>
    )
}
