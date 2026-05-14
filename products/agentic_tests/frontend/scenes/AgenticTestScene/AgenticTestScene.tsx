import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconBolt } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    LemonTag,
    LemonTagType,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    AgenticTestAssertion,
    AgenticTestAssertionType,
    ASSERTION_TYPE_LABELS,
    defaultAssertion,
} from '../../assertions'
import { agenticTestSceneLogic, AgenticTestSceneProps } from './agenticTestSceneLogic'

const SCHEDULE_PRESETS: { value: string; label: string }[] = [
    { value: '', label: 'Manual only' },
    { value: '*/5 * * * *', label: 'Every 5 minutes' },
    { value: '*/15 * * * *', label: 'Every 15 minutes' },
    { value: '*/30 * * * *', label: 'Every 30 minutes' },
    { value: '0 * * * *', label: 'Every hour' },
    { value: '0 */6 * * *', label: 'Every 6 hours' },
    { value: '0 0 * * *', label: 'Every day' },
]

const STATUS_BADGE: Record<string, { type: LemonTagType; label: string }> = {
    active: { type: 'success', label: 'Active' },
    paused: { type: 'warning', label: 'Paused' },
    proposed: { type: 'primary', label: 'Proposed' },
    rejected: { type: 'danger', label: 'Rejected' },
}

type AgenticTestTab = 'configuration' | 'runs'

const STATUS_TAG: Record<string, { type: LemonTagType; label: string }> = {
    passed: { type: 'success', label: 'Passed' },
    failed: { type: 'danger', label: 'Failed' },
    running: { type: 'primary', label: 'Running' },
    timeout: { type: 'warning', label: 'Timeout' },
    error: { type: 'danger', label: 'Error' },
}

const ASSERTION_TYPE_OPTIONS: { value: AgenticTestAssertionType; label: string }[] = (
    Object.entries(ASSERTION_TYPE_LABELS) as [AgenticTestAssertionType, string][]
).map(([value, label]) => ({ value, label }))

interface AssertionsEditorProps {
    assertions: AgenticTestAssertion[]
    onAdd: (type: AgenticTestAssertionType) => void
    onUpdate: (index: number, patch: Partial<AgenticTestAssertion>) => void
    onRemove: (index: number) => void
}

function AssertionsEditor({ assertions, onAdd, onUpdate, onRemove }: AssertionsEditorProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {assertions.map((assertion, idx) => (
                <div key={idx} className="border rounded p-2 flex flex-wrap items-center gap-2 bg-bg-light">
                    <span className="text-xs text-muted w-6">#{idx + 1}</span>
                    <LemonSelect
                        size="small"
                        value={assertion.type}
                        options={ASSERTION_TYPE_OPTIONS}
                        onChange={(value) => {
                            if (value && value !== assertion.type) {
                                onUpdate(idx, defaultAssertion(value as AgenticTestAssertionType))
                            }
                        }}
                        data-attr={`assertion-${idx}-type`}
                    />
                    {assertion.type === 'url_contains' && (
                        <LemonInput
                            size="small"
                            placeholder="/success"
                            value={assertion.value}
                            onChange={(v) => onUpdate(idx, { value: v } as Partial<AgenticTestAssertion>)}
                            data-attr={`assertion-${idx}-value`}
                        />
                    )}
                    {assertion.type === 'event_captured' && (
                        <>
                            <LemonInput
                                size="small"
                                placeholder="$purchase"
                                value={assertion.event}
                                onChange={(v) => onUpdate(idx, { event: v } as Partial<AgenticTestAssertion>)}
                                data-attr={`assertion-${idx}-event`}
                            />
                            <span className="text-xs text-muted">within</span>
                            <LemonInput
                                size="small"
                                type="number"
                                min={1}
                                max={3600}
                                value={assertion.within_seconds}
                                onChange={(v) =>
                                    onUpdate(idx, {
                                        within_seconds: Number(v) || 30,
                                    } as Partial<AgenticTestAssertion>)
                                }
                                data-attr={`assertion-${idx}-within`}
                            />
                            <span className="text-xs text-muted">seconds</span>
                        </>
                    )}
                    <div className="grow" />
                    <LemonButton
                        size="xsmall"
                        status="danger"
                        onClick={() => onRemove(idx)}
                        data-attr={`assertion-${idx}-remove`}
                    >
                        Remove
                    </LemonButton>
                </div>
            ))}
            <LemonButton size="small" type="secondary" onClick={() => onAdd('url_contains')} data-attr="assertion-add">
                + Add assertion
            </LemonButton>
        </div>
    )
}

function CardSection({
    title,
    icon,
    headerExtra,
    children,
}: {
    title: string
    icon?: JSX.Element
    headerExtra?: JSX.Element
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="border rounded p-3 bg-surface-primary flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 font-semibold">
                    {icon}
                    <span>{title}</span>
                </div>
                {headerExtra}
            </div>
            {children}
        </div>
    )
}

function ConfigurationTab({ id }: { id: string | 'new' }): JSX.Element {
    const logic = agenticTestSceneLogic({ id })
    const { test, testForm, isNew } = useValues(logic)
    const { setTestFormValue, addAssertion, updateAssertion, removeAssertion } = useActions(logic)

    const persistedStatus = test?.status ?? 'proposed'
    const statusBadge = STATUS_BADGE[persistedStatus] ?? {
        type: 'muted' as LemonTagType,
        label: persistedStatus,
    }
    const draftEnabled = testForm.status === 'active'
    const togglableStatus = persistedStatus === 'active' || persistedStatus === 'paused'

    return (
        <Form logic={agenticTestSceneLogic} props={{ id }} formKey="testForm">
            <div className="flex flex-wrap gap-4 items-start">
                <div className="flex flex-col flex-1 gap-4 min-w-80">
                    <CardSection
                        title="Status"
                        headerExtra={
                            !isNew ? <LemonTag type={statusBadge.type}>{statusBadge.label}</LemonTag> : undefined
                        }
                    >
                        {!isNew && togglableStatus ? (
                            <LemonSwitch
                                bordered
                                fullWidth
                                checked={draftEnabled}
                                onChange={(checked) => setTestFormValue('status', checked ? 'active' : 'paused')}
                                label="Enable test"
                                tooltip={
                                    draftEnabled
                                        ? 'Will run on schedule once saved.'
                                        : 'Paused. The test will not run automatically.'
                                }
                            />
                        ) : !isNew ? (
                            <p className="text-xs text-muted mb-0">
                                {persistedStatus === 'proposed'
                                    ? 'Accepting this proposal will enable the test and start running it on schedule.'
                                    : 'This test is rejected. Restore it from the list view to re-enable.'}
                            </p>
                        ) : (
                            <p className="text-xs text-muted mb-0">
                                Save the test first, then enable it to start running on schedule.
                            </p>
                        )}
                        {test?.next_run_at && persistedStatus === 'active' && (
                            <div className="text-xs text-muted">
                                Next run: <TZLabel time={test.next_run_at} />
                            </div>
                        )}
                    </CardSection>

                    <CardSection title="Trigger" icon={<IconBolt className="text-lg" />}>
                        <LemonLabel>Run cadence</LemonLabel>
                        <LemonSelect
                            value={testForm.schedule_cron ?? ''}
                            options={SCHEDULE_PRESETS}
                            onChange={(val) => setTestFormValue('schedule_cron', val ?? '')}
                            fullWidth
                            data-attr="agentic-test-schedule"
                        />
                        <p className="text-xs text-muted mb-0">
                            How often this test should run. Manual-only tests can be triggered with Run now.
                        </p>
                    </CardSection>

                    <CardSection title="Assertions">
                        <p className="text-xs text-muted mb-0">
                            Extra checks the run must satisfy on top of the agent's own self-evaluation. Pulled from
                            PostHog data — events, logs, errors — not just what the browser shows.
                        </p>
                        <AssertionsEditor
                            assertions={testForm.assertions ?? []}
                            onAdd={addAssertion}
                            onUpdate={updateAssertion}
                            onRemove={removeAssertion}
                        />
                    </CardSection>
                </div>

                <div className="flex flex-col flex-2 gap-4 min-w-100">
                    <CardSection title="Test definition">
                        <Field name="target_url" label="Target URL">
                            <LemonInput placeholder="https://hedgebox-dummy.posthog.com" data-attr="agentic-test-url" />
                        </Field>
                        {test?.source_replay_id && (
                            <div className="text-xs text-muted">
                                Seeded from{' '}
                                <Link to={`/replay/${test.source_replay_id}`} data-attr="source-replay-link">
                                    session replay {test.source_replay_id.slice(0, 8)}…
                                </Link>
                            </div>
                        )}
                        <Field name="prompt" label="Prompt">
                            <LemonTextArea
                                placeholder="Sign in with test@hedgebox.dev, upload demo.pdf, and verify the file appears in the recent uploads list."
                                minRows={20}
                                maxRows={40}
                                className="text-base"
                                data-attr="agentic-test-prompt"
                            />
                        </Field>
                    </CardSection>
                </div>
            </div>
        </Form>
    )
}

function RunsTab({ id }: { id: string | 'new' }): JSX.Element {
    const logic = agenticTestSceneLogic({ id })
    const { runs, runsLoading, logsUrl } = useValues(logic)

    return (
        <section>
            <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold">Run history</h3>
                {logsUrl && (
                    <Link to={logsUrl} data-attr="agentic-test-logs-link">
                        View logs for this test →
                    </Link>
                )}
            </div>
            <LemonTable
                dataSource={runs}
                loading={runsLoading}
                rowKey="id"
                emptyState="No runs yet — hit Run now to execute the prompt."
                columns={[
                    {
                        title: 'Started',
                        key: 'started_at',
                        render: (_, run) => <TZLabel time={run.started_at} />,
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, run) => {
                            const s = STATUS_TAG[run.status] ?? {
                                type: 'muted' as LemonTagType,
                                label: run.status,
                            }
                            return <LemonTag type={s.type}>{s.label}</LemonTag>
                        },
                    },
                    {
                        title: 'Duration',
                        key: 'duration_ms',
                        render: (_, run) => (run.duration_ms != null ? `${run.duration_ms} ms` : '—'),
                    },
                    {
                        title: 'Session',
                        key: 'external_session_id',
                        render: (_, run) =>
                            run.external_session_id ? (
                                <code className="text-xs">{run.external_session_id}</code>
                            ) : (
                                <span className="text-muted">—</span>
                            ),
                    },
                    {
                        title: 'Error',
                        key: 'error_message',
                        render: (_, run) =>
                            run.error_message ? (
                                <span className="text-xs text-danger">{run.error_message.slice(0, 140)}</span>
                            ) : (
                                <span className="text-muted">—</span>
                            ),
                    },
                ]}
            />
        </section>
    )
}

export function AgenticTestScene({ id }: AgenticTestSceneProps): JSX.Element {
    const logic = agenticTestSceneLogic({ id })
    const { test, testForm, isNew, testFormChanged, isTestFormSubmitting, willChangeEnabledOnSave } = useValues(logic)
    const { runNow, activate, reject, submitTestForm, setTestFormValue, clearChanges } = useActions(logic)
    const { searchParams } = useValues(router)
    const currentTab: AgenticTestTab = (searchParams.tab as AgenticTestTab) || 'configuration'

    const saveLabel = (() => {
        if (isNew) {
            return 'Create test'
        }
        if (willChangeEnabledOnSave) {
            return `Save & ${testForm.status === 'active' ? 'enable' : 'disable'}`
        }
        return 'Save changes'
    })()

    const tabs: LemonTab<AgenticTestTab>[] = [
        {
            label: 'Configuration',
            key: 'configuration',
            content: <ConfigurationTab id={id} />,
        },
        {
            label: 'Runs',
            key: 'runs',
            content: <RunsTab id={id} />,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={testForm.name ?? ''}
                description={testForm.description ?? ''}
                resourceType={{ type: 'agentic_tests' }}
                canEdit
                onNameChange={(name) => setTestFormValue('name', name)}
                onDescriptionChange={(description) => setTestFormValue('description', description)}
                renameDebounceMs={200}
                forceBackTo={{ key: 'AgenticTests', name: 'Agentic tests', path: '/agentic_tests' }}
                actions={
                    <>
                        {!isNew && test?.status === 'proposed' && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={reject}
                                data-attr="agentic-test-reject-detail"
                            >
                                Reject proposal
                            </LemonButton>
                        )}
                        {!isNew && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={runNow}
                                data-attr="agentic-test-run-now-detail"
                            >
                                Run now
                            </LemonButton>
                        )}
                        {!isNew && testFormChanged && test?.status !== 'proposed' && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                htmlType="reset"
                                onClick={() => clearChanges()}
                                disabledReason={isTestFormSubmitting ? 'Saving in progress…' : undefined}
                                data-attr="agentic-test-clear-changes"
                            >
                                Clear changes
                            </LemonButton>
                        )}
                        {test?.status === 'proposed' ? (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={activate}
                                data-attr="agentic-test-accept-detail"
                            >
                                Accept proposal
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                size="small"
                                htmlType="submit"
                                onClick={submitTestForm}
                                loading={isTestFormSubmitting}
                                disabledReason={!testFormChanged && !isNew ? 'No changes' : undefined}
                                data-attr="agentic-test-save"
                            >
                                {saveLabel}
                            </LemonButton>
                        )}
                    </>
                }
            />
            {test?.status === 'proposed' && (
                <LemonBanner type="info" className="mb-4">
                    This test was proposed by an agent based on a session replay. Review the prompt and accept it to add
                    it to your active tests.
                </LemonBanner>
            )}
            {isNew ? (
                <ConfigurationTab id={id} />
            ) : (
                <LemonTabs
                    activeKey={currentTab}
                    onChange={(tab) =>
                        router.actions.push(`/agentic_tests/${id}${tab === 'configuration' ? '' : `?tab=${tab}`}`)
                    }
                    tabs={tabs}
                    sceneInset
                />
            )}
        </SceneContent>
    )
}

export const scene: SceneExport<AgenticTestSceneProps> = {
    component: AgenticTestScene,
    logic: agenticTestSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? 'new' }),
}

export default AgenticTestScene
