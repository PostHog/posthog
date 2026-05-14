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

import { AgenticTestApi as AgenticTest } from '../../generated/api.schemas'
import { agenticTestsSceneLogic, StatusFilter } from './agenticTestsSceneLogic'
import { DetectFlowsBanner } from './DetectFlowsBanner'
import { DetectFlowsFormModal } from './DetectFlowsFormModal'
import { detectFlowsLogic } from './detectFlowsLogic'
import { DetectFlowsLogsModal } from './DetectFlowsLogsModal'

const RUN_STATUS_TAG: Record<string, { type: LemonTagType; label: string }> = {
    passed: { type: 'success', label: 'Passing' },
    failed: { type: 'danger', label: 'Failing' },
    running: { type: 'primary', label: 'Running' },
    timeout: { type: 'warning', label: 'Timeout' },
    error: { type: 'danger', label: 'Error' },
}

function runStatusFor(test: AgenticTest): { type: LemonTagType; label: string } {
    if (test.status === 'proposed') {
        return { type: 'warning', label: 'Proposed' }
    }
    if (test.status === 'rejected') {
        return { type: 'muted', label: 'Rejected' }
    }
    if (test.status === 'paused') {
        return { type: 'muted', label: 'Paused' }
    }
    if (!test.last_run) {
        return { type: 'muted', label: 'Pending' }
    }
    const lastRunStatus = String((test.last_run as { status?: string }).status ?? '')
    return RUN_STATUS_TAG[lastRunStatus] ?? { type: 'muted', label: lastRunStatus || 'Unknown' }
}

export function AgenticTestsScene(): JSX.Element {
    const { testsLoading, filteredTests, searchTerm, statusFilter } = useValues(agenticTestsSceneLogic)
    const { deleteTest, runNow, pauseTest, activateTest, rejectTest, setSearchTerm, setStatusFilter } =
        useActions(agenticTestsSceneLogic)
    const { openFormModal } = useActions(detectFlowsLogic)

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
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={openFormModal}
                            data-attr="agentic-tests-detect-flows"
                        >
                            Auto-detect flows
                        </LemonButton>
                        <LemonButton type="primary" size="small" to="/agentic_tests/new" data-attr="agentic-tests-new">
                            New test
                        </LemonButton>
                    </>
                }
            />

            <div className="flex justify-between gap-2 flex-wrap mb-4">
                <LemonInput type="search" placeholder="Search for tests" onChange={setSearchTerm} value={searchTerm} />
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
                            { label: 'Proposed', value: 'proposed' },
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
                emptyState="No tests yet — auto-detect flows or create your own."
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
                            const s = runStatusFor(test)
                            return (
                                <Tooltip title={test.last_run?.error_message || ''}>
                                    <LemonTag type={s.type}>{s.label}</LemonTag>
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
                        render: (_, test) =>
                            test.status === 'proposed' ? (
                                <div className="flex items-center gap-1 justify-end">
                                    <LemonButton
                                        size="xsmall"
                                        type="primary"
                                        to={`/agentic_tests/${test.id}`}
                                        data-attr="agentic-test-review"
                                    >
                                        Review
                                    </LemonButton>
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton fullWidth onClick={() => activateTest(test.id)}>
                                                    Accept
                                                </LemonButton>
                                                <LemonDivider />
                                                <LemonButton
                                                    fullWidth
                                                    status="danger"
                                                    onClick={() => confirmReject(test)}
                                                >
                                                    Reject
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                </div>
                            ) : (
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

            <DetectFlowsFormModal />
            <DetectFlowsLogsModal />
            <DetectFlowsBanner />
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: AgenticTestsScene,
    logic: agenticTestsSceneLogic,
}

export default AgenticTestsScene
