import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTag,
    LemonTagType,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
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

function ribbonColorFor(test: AgenticTest): string | undefined {
    if (test.status === 'proposed') {
        return 'var(--color-warning)'
    }
    const lastRunStatus = (test.last_run as { status?: string } | null)?.status
    if (lastRunStatus === 'failed' || lastRunStatus === 'error') {
        return 'var(--color-danger)'
    }
    return undefined
}

function HealthSummary({
    tests,
    passingCount,
    failingCount,
    proposedCount,
}: {
    tests: AgenticTest[]
    passingCount: number
    failingCount: number
    proposedCount: number
}): JSX.Element | null {
    if (tests.length === 0) {
        return null
    }
    const activeCount = tests.filter((t) => t.status === 'active').length

    return (
        <div className="flex items-center gap-4 text-sm mb-4">
            <span>
                <strong>{activeCount}</strong>
                <span className="text-secondary ml-1">active</span>
            </span>
            <span>
                <strong className={passingCount > 0 ? 'text-success' : ''}>{passingCount}</strong>
                <span className="text-secondary ml-1">passing</span>
            </span>
            <span>
                <strong className={failingCount > 0 ? 'text-danger' : ''}>{failingCount}</strong>
                <span className="text-secondary ml-1">failing</span>
            </span>
            {proposedCount > 0 && (
                <span>
                    <strong className="text-warning">{proposedCount}</strong>
                    <span className="text-secondary ml-1">to review</span>
                </span>
            )}
        </div>
    )
}

function EmptyState(): JSX.Element {
    const { openFormModal } = useActions(detectFlowsLogic)
    const { bannerVisible, isTerminal } = useValues(detectFlowsLogic)

    return (
        <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
            <h3 className="text-lg font-semibold mb-2">No tests running yet</h3>
            <p className="text-secondary text-sm mb-6 max-w-md">
                Agentic tests use browser agents to continuously verify your product's key flows in production. Start by
                auto-detecting what matters most.
            </p>
            <div className="flex gap-2">
                <LemonButton
                    type="primary"
                    icon={<IconSparkles />}
                    onClick={openFormModal}
                    disabledReason={bannerVisible && !isTerminal ? 'Detection already in progress' : undefined}
                >
                    Auto-detect key flows
                </LemonButton>
                <LemonButton type="tertiary" to="/agentic_tests/new">
                    Create manually
                </LemonButton>
            </div>
        </div>
    )
}

export function AgenticTestsScene(): JSX.Element {
    const { tests, testsLoading, filteredTests, passingCount, failingCount, proposedCount, searchTerm, statusFilter } =
        useValues(agenticTestsSceneLogic)
    const { deleteTest, runNow, pauseTest, activateTest, rejectTest, setSearchTerm, setStatusFilter } =
        useActions(agenticTestsSceneLogic)
    const { openFormModal } = useActions(detectFlowsLogic)
    const { bannerVisible, isTerminal: detectionTerminal } = useValues(detectFlowsLogic)

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

    const hasTests = tests.length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name="Agentic tests"
                description="Continuous browser-agent checks against your product's key flows."
                resourceType={{ type: 'agentic_tests' }}
                actions={
                    hasTests ? (
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconSparkles />}
                                onClick={openFormModal}
                                disabledReason={
                                    bannerVisible && !detectionTerminal ? 'Detection already in progress' : undefined
                                }
                                data-attr="agentic-tests-detect-flows"
                            >
                                Auto-detect key flows
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                to="/agentic_tests/new"
                                data-attr="agentic-tests-new"
                            >
                                New test
                            </LemonButton>
                        </>
                    ) : undefined
                }
            />

            {hasTests ? (
                <>
                    <HealthSummary
                        tests={tests}
                        passingCount={passingCount}
                        failingCount={failingCount}
                        proposedCount={proposedCount}
                    />

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
                        rowRibbonColor={(test) => ribbonColorFor(test)}
                        emptyState="No tests match this filter."
                        columns={[
                            {
                                title: 'Test',
                                key: 'name',
                                render: (_, test) => (
                                    <LemonTableLink
                                        to={`/agentic_tests/${test.id}`}
                                        title={<span data-attr="agentic-test-row-link">{test.name}</span>}
                                        description={
                                            test.target_url ? (
                                                <span className="font-mono">{test.target_url}</span>
                                            ) : undefined
                                        }
                                    />
                                ),
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                width: 120,
                                render: (_, test) => {
                                    const s = runStatusFor(test)
                                    const errorMessage = String(
                                        (test.last_run as { error_message?: string } | null)?.error_message ?? ''
                                    )
                                    return (
                                        <Tooltip title={errorMessage}>
                                            <LemonTag type={s.type}>{s.label}</LemonTag>
                                        </Tooltip>
                                    )
                                },
                            },
                            {
                                title: 'Last run',
                                key: 'last_run',
                                width: 160,
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
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() => pauseTest(test.id)}
                                                                >
                                                                    Pause
                                                                </LemonButton>
                                                            ) : (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() => activateTest(test.id)}
                                                                >
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
                </>
            ) : (
                !testsLoading && <EmptyState />
            )}

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
