import { useActions, useValues } from 'kea'

import { LemonSkeleton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { type TaskSummary } from '../api'
import { automlLogic } from './automlLogic'
import { MetricsInline, SpecOneLiner } from './specView'

export const scene: SceneExport = {
    component: AutoMLTasksScene,
    logic: automlLogic,
}

export default function AutoMLTasksScene(): JSX.Element {
    const { tasks, tasksLoading } = useValues(automlLogic)
    const { loadTasks } = useActions(automlLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="AutoML"
                description="Tasks the AutoML pipeline has written to S3."
                resourceType={{ type: 'task' }}
                actions={<LemonButton onClick={() => loadTasks()}>Refresh</LemonButton>}
            />
            {tasksLoading && tasks.length === 0 ? (
                <LemonSkeleton className="h-32" />
            ) : (
                <LemonTable
                    dataSource={tasks}
                    rowKey="name"
                    emptyState="No AutoML tasks found in S3."
                    columns={[
                        {
                            title: 'Task',
                            dataIndex: 'name',
                            render: (_, task: TaskSummary) => (
                                <Link to={urls.automlTask(task.name)} className="font-semibold">
                                    {task.name}
                                </Link>
                            ),
                        },
                        {
                            title: 'Scope',
                            render: (_, task: TaskSummary) => <SpecOneLiner spec={task.spec} />,
                        },
                        {
                            title: 'Current query',
                            render: (_, task: TaskSummary) =>
                                task.current_query_version ? (
                                    <code className="text-xs">{stripSql(task.current_query_version)}</code>
                                ) : (
                                    <span className="text-muted">—</span>
                                ),
                        },
                        {
                            title: 'Current run',
                            render: (_, task: TaskSummary) => {
                                if (!task.current_run_id) {
                                    return <span className="text-muted">no shipped run</span>
                                }
                                return (
                                    <div className="flex flex-col gap-0.5">
                                        <Link to={urls.automlRun(task.name, task.current_run_id)} className="text-xs">
                                            <code>{task.current_run_id}</code>
                                        </Link>
                                        <MetricsInline manifest={task.current_run_manifest} />
                                    </div>
                                )
                            },
                        },
                        {
                            title: 'Runs',
                            render: (_, task: TaskSummary) => (
                                <LemonTag type={task.run_count > 0 ? 'primary' : 'muted'}>{task.run_count}</LemonTag>
                            ),
                        },
                    ]}
                />
            )}
        </SceneContent>
    )
}

function stripSql(version: string): string {
    return version.endsWith('.sql') ? version.slice(0, -4) : version
}
