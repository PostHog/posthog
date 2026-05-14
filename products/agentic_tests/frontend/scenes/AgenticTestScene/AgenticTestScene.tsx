import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

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

import { AGENTIC_TEST_REGION_OPTIONS } from '../../agenticTestRegions'
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

function formatDurationMs(ms: number): string {
    // Sub-second: show as ms ("420 ms"). Sub-minute: "12.4s". Else "1m 9s" / "2h 17m".
    if (ms < 1000) {
        return `${ms} ms`
    }
    const totalSeconds = Math.round(ms / 1000)
    if (totalSeconds < 60) {
        return `${(ms / 1000).toFixed(1)}s`
    }
    const minutes = Math.floor(totalSeconds / 60)
    const seconds = totalSeconds % 60
    if (minutes < 60) {
        return `${minutes}m ${seconds}s`
    }
    const hours = Math.floor(minutes / 60)
    const remainingMinutes = minutes % 60
    return `${hours}h ${remainingMinutes}m`
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
                    {(assertion.type === 'event_captured' || assertion.type === 'event_not_captured') && (
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
                    {assertion.type === 'no_console_errors' && (
                        <>
                            <span className="text-xs text-muted">at most</span>
                            <LemonInput
                                size="small"
                                type="number"
                                min={0}
                                max={1000}
                                value={assertion.max_errors}
                                onChange={(v) =>
                                    onUpdate(idx, {
                                        max_errors: Number(v) || 0,
                                    } as Partial<AgenticTestAssertion>)
                                }
                                data-attr={`assertion-${idx}-max-errors`}
                            />
                            <span className="text-xs text-muted">console error(s) during the run</span>
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
            <LemonButton
                size="small"
                type="secondary"
                onClick={() => onAdd('event_captured')}
                data-attr="assertion-add"
            >
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
    const { setTestFormValue, setAgenticTestFormRegion, addAssertion, updateAssertion, removeAssertion } =
        useActions(logic)

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
                        {test?.next_run_at &&
                            persistedStatus === 'active' &&
                            (new Date(test.next_run_at).getTime() > Date.now() ? (
                                <div className="text-xs text-muted">
                                    Next run: <TZLabel time={test.next_run_at} />
                                </div>
                            ) : (
                                <div className="text-xs text-warning">
                                    Overdue — scheduled for <TZLabel time={test.next_run_at} />. Check that the celery
                                    beat + worker are running.
                                </div>
                            ))}
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

                    <CardSection title="Regions">
                        <p className="text-xs text-muted mb-0">
                            Where this test runs from. Each trigger creates one run per selected region, so 3 regions =
                            3 parallel runs every time.
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                            {AGENTIC_TEST_REGION_OPTIONS.map((opt) => {
                                const regions = testForm.regions ?? []
                                const selected = regions.includes(opt.value)
                                const soleSelected = selected && regions.length === 1
                                return (
                                    <LemonButton
                                        key={opt.value}
                                        size="small"
                                        type={selected ? 'primary' : 'secondary'}
                                        disabledReason={
                                            soleSelected ? 'Add another region before deselecting this one' : undefined
                                        }
                                        onClick={() => setAgenticTestFormRegion(opt.value, !selected)}
                                        data-attr={`agentic-test-region-${opt.value}`}
                                    >
                                        {opt.label}
                                    </LemonButton>
                                )
                            })}
                        </div>
                        {(() => {
                            const count = (testForm.regions ?? []).length
                            if (count === 0) {
                                return (
                                    <p className="text-xs text-danger mb-0">
                                        Pick at least one region — the test needs somewhere to run from.
                                    </p>
                                )
                            }
                            return (
                                <p className="text-xs text-muted mb-0">
                                    {count === 1 ? '1 run per trigger.' : `${count} parallel runs per trigger.`}
                                </p>
                            )
                        })()}
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

function RunLogEntries({ entries, streaming }: { entries: any[]; streaming: boolean }): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)
    useEffect(() => {
        const el = ref.current
        if (el && streaming) {
            el.scrollTop = el.scrollHeight
        }
    }, [entries, streaming])

    if (!entries || entries.length === 0) {
        return (
            <div className="text-xs text-muted italic p-3">
                {streaming ? 'Waiting for the agent to emit its first event…' : 'No log entries captured for this run.'}
            </div>
        )
    }

    return (
        <div ref={ref} className="border rounded p-2 max-h-96 overflow-auto bg-bg-light font-mono text-xs">
            {entries.map((ev, idx) => {
                const type = ev.type ?? ev.event
                const data = ev.data ?? {}
                const step = data.step ?? ev.step
                return (
                    <div key={idx} className="py-0.5">
                        <span className="text-muted">[{type}]</span>{' '}
                        {step != null && <span className="text-muted">step {step} </span>}
                        {type === 'tool_call' ? (
                            <span>
                                <strong>{data.name}</strong>({JSON.stringify(data.input ?? {})})
                            </span>
                        ) : type === 'tool_result' ? (
                            <span className="text-muted">→ {String(data.result).slice(0, 200)}</span>
                        ) : type === 'model_text' ? (
                            <span className="text-muted italic">{data.text}</span>
                        ) : type === 'status' ? (
                            <span>
                                {data.message}{' '}
                                {data.replay_url && (
                                    <Link to={data.replay_url} target="_blank">
                                        (browserbase replay)
                                    </Link>
                                )}
                            </span>
                        ) : type === 'final' ? (
                            <span>
                                verdict: {data.passed ? '✓ passed' : '✗ failed'} —{' '}
                                {data.output?.verdict?.reason ?? data.error ?? ''}
                            </span>
                        ) : (
                            <span>{JSON.stringify(data)}</span>
                        )}
                    </div>
                )
            })}
            {streaming && <div className="text-muted italic">streaming…</div>}
        </div>
    )
}

function RunsTab({ id }: { id: string | 'new' }): JSX.Element {
    const logic = agenticTestSceneLogic({ id })
    const { runs, runsLoading, logsUrl, selectedRunId } = useValues(logic)
    const { setSelectedRunId } = useActions(logic)

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
                expandable={{
                    expandedRowRender: (run) => (
                        <div className="p-2">
                            <RunLogEntries
                                entries={(run as any).log_entries ?? []}
                                streaming={run.status === 'running'}
                            />
                        </div>
                    ),
                    rowExpandable: (run) => Boolean((run as any).log_entries?.length) || run.status === 'running',
                    noIndent: true,
                }}
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
                        render: (_, run) => (run.duration_ms != null ? formatDurationMs(run.duration_ms) : '—'),
                    },
                    {
                        title: 'Source',
                        key: 'source',
                        render: (_, run) =>
                            (run as any).source ? (
                                <LemonTag type={(run as any).source === 'scheduled' ? 'primary' : 'muted'}>
                                    {(run as any).source}
                                </LemonTag>
                            ) : (
                                <span className="text-muted">—</span>
                            ),
                    },
                    {
                        title: 'Region',
                        key: 'region',
                        render: (_, run) =>
                            (run as any).region ? (
                                <code className="text-xs">{(run as any).region}</code>
                            ) : (
                                <span className="text-muted">—</span>
                            ),
                    },
                    {
                        title: 'Replay',
                        key: 'posthog_session_id',
                        render: (_, run) => {
                            // Always render the "View replay →" link for demo purposes — if the
                            // session id isn't paired yet, the link points to an empty replay route
                            // and resolves once the pairing task completes.
                            const sid = (run as any).posthog_session_id as string | undefined
                            return (
                                <Link to={sid ? `/replay/${sid}` : '/replay'} data-attr="run-replay-link">
                                    View replay →
                                </Link>
                            )
                        },
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
                    {
                        title: '',
                        key: 'investigation',
                        render: (_, run) => {
                            const convId = (run as any).investigation_conversation_id as string | undefined
                            if (!convId) {
                                return null
                            }
                            return (
                                <LemonButton
                                    size="xsmall"
                                    type={selectedRunId === run.id ? 'primary' : 'tertiary'}
                                    onClick={() => setSelectedRunId(selectedRunId === run.id ? null : run.id)}
                                >
                                    Investigation
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
            {selectedRunId &&
                (() => {
                    const selectedRun = runs.find((r) => r.id === selectedRunId)
                    const convId = (selectedRun as any)?.investigation_conversation_id as string | undefined
                    return convId ? <InvestigationThread conversationId={convId} /> : null
                })()}
        </section>
    )
}

export function AgenticTestScene({ id }: AgenticTestSceneProps): JSX.Element {
    const logic = agenticTestSceneLogic({ id })
    const { test, testForm, isNew, testFormChanged, isTestFormSubmitting, willChangeEnabledOnSave, hasRunningRuns } =
        useValues(logic)
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
                                onClick={() => {
                                    runNow()
                                    if (currentTab !== 'runs') {
                                        router.actions.push(`/agentic_tests/${id}?tab=runs`)
                                    }
                                }}
                                loading={hasRunningRuns}
                                disabledReason={hasRunningRuns ? 'A run is already in progress' : undefined}
                                data-attr="agentic-test-run-detail"
                            >
                                Run
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
                />
            )}
        </SceneContent>
    )
}

function InvestigationThread({ conversationId }: { conversationId: string }): JSX.Element {
    return (
        <div className="mt-4 border rounded p-4">
            <h3 className="font-semibold mb-2">Investigation</h3>
            <p className="text-sm text-muted mb-3">
                PostHog AI is investigating this failure. View the full conversation in{' '}
                <Link to={`/ai/${conversationId}`}>PostHog AI</Link>.
            </p>
            <LemonButton type="primary" size="small" to={`/ai/${conversationId}`}>
                Open investigation thread
            </LemonButton>
        </div>
    )
}

export const scene: SceneExport<AgenticTestSceneProps> = {
    component: AgenticTestScene,
    logic: agenticTestSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? 'new' }),
}

export default AgenticTestScene
