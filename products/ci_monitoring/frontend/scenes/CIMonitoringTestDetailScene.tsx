import { useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FlakeScoreBar } from '../components/FlakeScoreBar'
import { TestStatusBadge } from '../components/TestStatusBadge'
import type { TestExecutionApi } from '../generated/api.schemas'
import {
    CIMonitoringTestDetailSceneLogicProps,
    ciMonitoringTestDetailSceneLogic,
} from './ciMonitoringTestDetailSceneLogic'

export const scene: SceneExport = {
    component: CIMonitoringTestDetailScene,
    logic: ciMonitoringTestDetailSceneLogic,
    paramsToProps: ({ params: { testId } }): CIMonitoringTestDetailSceneLogicProps => ({
        testId: testId || '',
    }),
}

function StatCard({ label, value }: { label: string; value: string | number }): JSX.Element {
    return (
        <div className="border rounded-lg p-4">
            <div className="text-xs text-muted uppercase font-medium">{label}</div>
            <div className="text-2xl font-bold mt-1">{value}</div>
        </div>
    )
}

function formatDuration(ms: number | null): string {
    if (ms === null) {
        return '-'
    }
    if (ms < 1000) {
        return `${ms}ms`
    }
    return `${(ms / 1000).toFixed(1)}s`
}

export function CIMonitoringTestDetailScene(): JSX.Element {
    const { testCase, testCaseLoading, executions, executionsLoading } = useValues(ciMonitoringTestDetailSceneLogic)

    const columns: LemonTableColumns<TestExecutionApi> = [
        {
            title: 'Status',
            key: 'status',
            width: 100,
            render: (_, exec) => <TestStatusBadge status={exec.status} />,
        },
        {
            title: 'Duration',
            key: 'duration_ms',
            width: 100,
            render: (_, exec) => <span className="font-mono text-xs">{formatDuration(exec.duration_ms)}</span>,
        },
        {
            title: 'Retries',
            key: 'retry_count',
            width: 80,
            render: (_, exec) => <span className="text-muted">{exec.retry_count > 0 ? exec.retry_count : '-'}</span>,
        },
        {
            title: 'Error',
            key: 'error_message',
            render: (_, exec) =>
                exec.error_message ? (
                    <span className="text-xs text-danger truncate max-w-md block">{exec.error_message}</span>
                ) : (
                    <span className="text-muted">-</span>
                ),
        },
        {
            title: 'Date',
            key: 'created_at',
            width: 120,
            render: (_, exec) => <span className="text-muted">{dayjs(exec.created_at).fromNow()}</span>,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={testCase?.identifier || 'Test details'}
                resourceType={{ type: 'ci_monitoring' }}
                isLoading={testCaseLoading}
            />

            {testCase && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                    <StatCard label="Flake score" value={`${(testCase.flake_score * 100).toFixed(0)}%`} />
                    <StatCard label="Total runs" value={testCase.total_runs} />
                    <StatCard label="Total flakes" value={testCase.total_flakes} />
                    <div className="border rounded-lg p-4">
                        <div className="text-xs text-muted uppercase font-medium">Score</div>
                        <div className="mt-2">
                            <FlakeScoreBar score={testCase.flake_score} />
                        </div>
                    </div>
                </div>
            )}

            <h3 className="text-lg font-semibold mt-6 mb-2">Recent executions</h3>

            <LemonTable
                dataSource={executions}
                columns={columns}
                loading={executionsLoading}
                pagination={{ pageSize: 20 }}
                nouns={['execution', 'executions']}
                emptyState="No executions found"
            />
        </SceneContent>
    )
}

export default CIMonitoringTestDetailScene
