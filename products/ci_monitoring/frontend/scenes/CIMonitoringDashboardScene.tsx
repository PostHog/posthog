import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTable, LemonTableColumns, LemonTabs } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { FlakeScoreBar } from '../components/FlakeScoreBar'
import { MainStreakCounter } from '../components/MainStreakCounter'
import { TestStatusBadge } from '../components/TestStatusBadge'
import type { TestCaseApi } from '../generated/api.schemas'
import { TestTab, ciMonitoringDashboardSceneLogic } from './ciMonitoringDashboardSceneLogic'

export const scene: SceneExport = {
    component: CIMonitoringDashboardScene,
    logic: ciMonitoringDashboardSceneLogic,
}

function testStatus(test: TestCaseApi): string {
    if (test.quarantine) {
        return 'quarantined'
    }
    if (test.flake_score > 0) {
        return 'flaky'
    }
    return 'passed'
}

export function CIMonitoringDashboardScene(): JSX.Element {
    const { tests, testsLoading, activeTab, streak, healthLoading } = useValues(ciMonitoringDashboardSceneLogic)
    const { setActiveTab } = useActions(ciMonitoringDashboardSceneLogic)

    const columns: LemonTableColumns<TestCaseApi> = [
        {
            title: 'Test',
            key: 'identifier',
            render: (_, test) => (
                <div className="min-w-0">
                    <div className="font-medium truncate">{test.identifier}</div>
                    {test.file_path && <div className="text-xs text-muted truncate">{test.file_path}</div>}
                </div>
            ),
        },
        {
            title: 'Suite',
            key: 'suite',
            width: 100,
            render: (_, test) => <span className="text-xs font-medium uppercase text-muted">{test.suite}</span>,
        },
        {
            title: 'Flake score',
            key: 'flake_score',
            width: 140,
            sorter: (a, b) => a.flake_score - b.flake_score,
            render: (_, test) => <FlakeScoreBar score={test.flake_score} />,
        },
        {
            title: 'Runs',
            key: 'total_runs',
            width: 80,
            sorter: (a, b) => a.total_runs - b.total_runs,
            render: (_, test) => <span className="text-muted">{test.total_runs}</span>,
        },
        {
            title: 'Last flaked',
            key: 'last_flaked_at',
            width: 120,
            render: (_, test) => (
                <span className="text-muted">
                    {test.last_flaked_at ? dayjs(test.last_flaked_at).fromNow() : 'Never'}
                </span>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            width: 100,
            render: (_, test) => <TestStatusBadge status={testStatus(test)} />,
        },
    ]

    const tabs: { key: TestTab; label: string }[] = [
        { key: 'needs_attention', label: 'Needs attention' },
        { key: 'all', label: 'All tests' },
        { key: 'quarantined', label: 'Quarantined' },
    ]

    return (
        <SceneContent>
            <SceneTitleSection name="CI monitoring" resourceType={{ type: 'ci_monitoring' }} />

            <MainStreakCounter streak={streak} loading={healthLoading} />

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key)}
                tabs={tabs.map(({ key, label }) => ({ key, label }))}
            />

            <LemonTable
                dataSource={tests}
                columns={columns}
                loading={testsLoading}
                pagination={{ pageSize: 20 }}
                nouns={['test', 'tests']}
                emptyState="No tests found"
                defaultSorting={{ columnKey: 'flake_score', order: -1 }}
                onRow={(test) => ({
                    onClick: () => router.actions.push(`/ci_monitoring/tests/${test.id}`),
                    className: 'cursor-pointer',
                })}
            />
        </SceneContent>
    )
}

export default CIMonitoringDashboardScene
