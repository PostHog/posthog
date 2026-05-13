import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTag,
    LemonTagType,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AgenticTest } from '../../types'
import { agenticTestsSceneLogic, StatusFilter } from './agenticTestsSceneLogic'

const RUN_STATUS_TAG: Record<string, { type: LemonTagType; label: string }> = {
    passed: { type: 'success', label: 'Passing' },
    failed: { type: 'danger', label: 'Failing' },
    running: { type: 'primary', label: 'Running' },
    timeout: { type: 'warning', label: 'Timeout' },
    error: { type: 'danger', label: 'Error' },
}

function runStatusFor(test: AgenticTest): { type: LemonTagType; label: string } {
    if (test.status === 'rejected') {
        return { type: 'muted', label: 'Rejected' }
    }
    if (test.status === 'paused') {
        return { type: 'muted', label: 'Paused' }
    }
    if (!test.last_run) {
        return { type: 'muted', label: 'Pending' }
    }
    return RUN_STATUS_TAG[test.last_run.status] ?? { type: 'muted', label: test.last_run.status }
}

export function AgenticTestsScene(): JSX.Element {
    const { testsLoading, proposedTests, filteredTests, searchTerm, statusFilter } = useValues(agenticTestsSceneLogic)
    const { deleteTest, runNow, pauseTest, activateTest, rejectTest, setSearchTerm, setStatusFilter } =
        useActions(agenticTestsSceneLogic)

    const confirmReject = (test: AgenticTest): void => {
        LemonDialog.open({
            title: `Reject "${test.name}"?`,
            description:
                'The test will be kept in a rejected state — you can restore it later from the Rejected filter.',
            primaryButton: {
                children: 'Reject',
                status: 'danger',
                onClick: () => rejectTest(test.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const confirmDelete = (test: AgenticTest): void => {
        LemonDialog.open({
            title: `Delete "${test.name}"?`,
            description: 'The test and its full run history will be permanently deleted.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteTest(test.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Agentic tests"
                description="LLM-driven browser checks against your product, seeded by session replays."
                resourceType={{ type: 'agentic_tests' }}
                actions={
                    <LemonButton type="primary" size="small" to="/agentic_tests/new" data-attr="agentic-tests-new">
                        New test
                    </LemonButton>
                }
            />

            {proposedTests.length > 0 && (
                <section className="mb-8">
                    <h3 className="font-semibold mb-2">Proposed by PostHog AI</h3>
                    <p className="text-xs text-muted mb-3">
                        Generated from session replays. Review the prompt, then accept to start running them.
                    </p>
                    <LemonTable
                        dataSource={proposedTests}
                        rowKey="id"
                        columns={[
                            {
                                title: 'Name',
                                key: 'name',
                                render: (_, test) => (
                                    <Link
                                        to={`/agentic_tests/${test.id}`}
                                        className="font-semibold"
                                        data-attr="agentic-test-row-link"
                                    >
                                        {test.name}
                                    </Link>
                                ),
                            },
                            {
                                title: 'Source',
                                key: 'source',
                                render: (_, test) =>
                                    test.source_replay_id ? (
                                        <Link to={`/replay/${test.source_replay_id}`}>
                                            replay {test.source_replay_id.slice(0, 8)}…
                                        </Link>
                                    ) : (
                                        <span className="text-muted">—</span>
                                    ),
                            },
                            {
                                title: 'Created',
                                key: 'created_at',
                                render: (_, test) => <TZLabel time={test.created_at} />,
                            },
                            {
                                width: 0,
                                render: (_, test) => (
                                    <div className="flex items-center gap-1 justify-end">
                                        <LemonButton
                                            size="xsmall"
                                            type="primary"
                                            onClick={() => activateTest(test.id)}
                                            data-attr="agentic-test-accept"
                                        >
                                            Accept
                                        </LemonButton>
                                        <LemonButton
                                            size="xsmall"
                                            status="danger"
                                            onClick={() => confirmReject(test)}
                                            data-attr="agentic-test-reject"
                                        >
                                            Reject
                                        </LemonButton>
                                        <More
                                            overlay={
                                                <LemonButton
                                                    fullWidth
                                                    to={`/agentic_tests/${test.id}`}
                                                    data-attr="agentic-test-view"
                                                >
                                                    Review prompt
                                                </LemonButton>
                                            }
                                        />
                                    </div>
                                ),
                            },
                        ]}
                    />
                </section>
            )}

            <section>
                <h3 className="font-semibold mb-2">Tests</h3>
                <div className="flex justify-between gap-2 flex-wrap mb-4">
                    <LemonInput
                        type="search"
                        placeholder="Search for tests"
                        onChange={setSearchTerm}
                        value={searchTerm}
                    />
                    <div className="flex items-center gap-2">
                        <span>
                            <b>Status</b>
                        </span>
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            size="small"
                            onChange={(value) => setStatusFilter(value as StatusFilter)}
                            options={[
                                { label: 'All', value: 'all' },
                                { label: 'Active', value: 'active' },
                                { label: 'Paused', value: 'paused' },
                                { label: 'Rejected', value: 'rejected' },
                            ]}
                            value={statusFilter}
                        />
                    </div>
                </div>
                <LemonTable
                    dataSource={filteredTests}
                    loading={testsLoading}
                    rowKey="id"
                    emptyState="No active tests yet — accept a proposed one or create your own."
                    columns={[
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, test) => (
                                <Link
                                    to={`/agentic_tests/${test.id}`}
                                    className="font-semibold"
                                    data-attr="agentic-test-row-link"
                                >
                                    {test.name}
                                </Link>
                            ),
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, test) => {
                                const status = runStatusFor(test)
                                return (
                                    <Tooltip title={test.last_run?.error_message || ''}>
                                        <LemonTag type={status.type}>{status.label}</LemonTag>
                                    </Tooltip>
                                )
                            },
                        },
                        {
                            title: 'Last run',
                            key: 'last_run',
                            render: (_, test) =>
                                test.last_run_at ? (
                                    <TZLabel time={test.last_run_at} />
                                ) : (
                                    <span className="text-muted">—</span>
                                ),
                        },
                        {
                            width: 0,
                            render: (_, test) => (
                                <More
                                    overlay={
                                        <>
                                            {test.status === 'rejected' ? (
                                                <LemonButton fullWidth onClick={() => activateTest(test.id)}>
                                                    Restore
                                                </LemonButton>
                                            ) : (
                                                <>
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => runNow(test.id)}
                                                        data-attr="agentic-test-run-now"
                                                    >
                                                        Run now
                                                    </LemonButton>
                                                    {test.status === 'active' ? (
                                                        <LemonButton fullWidth onClick={() => pauseTest(test.id)}>
                                                            Pause
                                                        </LemonButton>
                                                    ) : (
                                                        <LemonButton fullWidth onClick={() => activateTest(test.id)}>
                                                            Resume
                                                        </LemonButton>
                                                    )}
                                                </>
                                            )}
                                            <LemonDivider />
                                            <LemonButton
                                                fullWidth
                                                status="danger"
                                                onClick={() => confirmDelete(test)}
                                                data-attr="agentic-test-delete"
                                            >
                                                Delete
                                            </LemonButton>
                                        </>
                                    }
                                />
                            ),
                        },
                    ]}
                />
            </section>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: AgenticTestsScene,
    logic: agenticTestsSceneLogic,
}

export default AgenticTestsScene
