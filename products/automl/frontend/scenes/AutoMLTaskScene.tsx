import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { type RunSummary } from '../api'
import { automlLogic } from './automlLogic'
import { MetricsInline, SpecSummary } from './specView'

export const scene: SceneExport = {
    component: AutoMLTaskScene,
    logic: automlLogic,
}

export default function AutoMLTaskScene(): JSX.Element {
    const { taskDetail, taskDetailLoading, selectedQuery, queryText, queryTextLoading } = useValues(automlLogic)
    const { setSelectedQuery } = useActions(automlLogic)

    if (taskDetailLoading && !taskDetail) {
        return <LemonSkeleton className="h-64" />
    }
    if (!taskDetail) {
        return <NotFound object="AutoML task" />
    }

    const activeQuery = selectedQuery ?? taskDetail.current_query_version ?? taskDetail.queries[0] ?? null

    return (
        <SceneContent>
            <SceneTitleSection
                name={taskDetail.name}
                description="Task spec, query versions, and training runs."
                resourceType={{ type: 'task' }}
            />

            <Section title="Spec">
                {taskDetail.spec ? (
                    <SpecSummary spec={taskDetail.spec} />
                ) : (
                    <p className="text-muted">No spec.yaml found.</p>
                )}
            </Section>

            <Section title="Queries">
                {taskDetail.queries.length === 0 ? (
                    <p className="text-muted">No queries written yet.</p>
                ) : (
                    <>
                        <div className="flex items-center gap-2 mb-2">
                            <LemonSelect
                                value={activeQuery}
                                options={taskDetail.queries.map((q) => ({
                                    value: q,
                                    label:
                                        q === taskDetail.current_query_version ? (
                                            <span>
                                                {stripSql(q)} <LemonTag type="success">HEAD</LemonTag>
                                            </span>
                                        ) : (
                                            stripSql(q)
                                        ),
                                }))}
                                onChange={(value) => setSelectedQuery(value)}
                            />
                        </div>
                        {queryTextLoading ? (
                            <LemonSkeleton className="h-32" />
                        ) : queryText ? (
                            <pre className="bg-bg-light border rounded p-3 overflow-x-auto text-xs">
                                {queryText.sql}
                            </pre>
                        ) : (
                            <p className="text-muted">Pick a query version above.</p>
                        )}
                    </>
                )}
            </Section>

            <Section title="Runs">
                <LemonTable
                    dataSource={taskDetail.runs}
                    rowKey="id"
                    emptyState="No runs recorded yet."
                    columns={[
                        {
                            title: 'Run',
                            dataIndex: 'id',
                            render: (_, run: RunSummary) => (
                                <Link to={urls.automlRun(taskDetail.name, run.id)} className="text-xs">
                                    <code>{run.id}</code>
                                </Link>
                            ),
                        },
                        {
                            title: 'Status',
                            render: (_, run: RunSummary) => (
                                <div className="flex gap-1 flex-wrap">
                                    {run.shipped && <LemonTag type="success">shipped</LemonTag>}
                                    {run.is_current && <LemonTag type="primary">current</LemonTag>}
                                    {!run.shipped && !run.is_current && <LemonTag type="muted">historical</LemonTag>}
                                </div>
                            ),
                        },
                        {
                            title: 'Scores',
                            render: (_, run: RunSummary) => <MetricsInline manifest={run.manifest} />,
                        },
                    ]}
                />
            </Section>
        </SceneContent>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <h3 className="text-base font-semibold m-0">{title}</h3>
            {children}
        </section>
    )
}

function stripSql(version: string): string {
    return version.endsWith('.sql') ? version.slice(0, -4) : version
}
