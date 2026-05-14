import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { useEffect, useRef } from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTag,
    LemonTagType,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
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

export function AgenticTestScene({ id }: AgenticTestSceneProps): JSX.Element {
    const logic = agenticTestSceneLogic({ id })
    const { test, testForm, runs, runsLoading, isNew, logsUrl, liveEvents, streaming } = useValues(logic)
    const liveLogRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        const el = liveLogRef.current
        if (el) {
            el.scrollTop = el.scrollHeight
        }
    }, [liveEvents])
    const {
        streamRun,
        clearLiveEvents,
        activate,
        pause,
        reject,
        submitTestForm,
        setTestFormValue,
        addAssertion,
        updateAssertion,
        removeAssertion,
    } = useActions(logic)

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
                        {!isNew && test?.status === 'active' && (
                            <LemonButton type="secondary" size="small" onClick={pause}>
                                Pause
                            </LemonButton>
                        )}
                        {!isNew && test?.status === 'paused' && (
                            <LemonButton type="secondary" size="small" onClick={activate}>
                                Resume
                            </LemonButton>
                        )}
                        {!isNew && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={streamRun}
                                loading={streaming}
                                disabledReason={streaming ? 'A run is already in progress' : undefined}
                                data-attr="agentic-test-run-detail"
                            >
                                Run
                            </LemonButton>
                        )}
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
                        {!isNew && test?.status === 'proposed' ? (
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
                                onClick={submitTestForm}
                                data-attr="agentic-test-save"
                            >
                                {isNew ? 'Create test' : 'Save changes'}
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
            <Form logic={agenticTestSceneLogic} props={{ id }} formKey="testForm">
                <div className="flex flex-col gap-4 max-w-3xl">
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
                            minRows={6}
                            maxRows={24}
                            className="text-base"
                            data-attr="agentic-test-prompt"
                        />
                    </Field>
                    <p className="text-xs text-muted -mt-2">
                        Natural-language instructions the browser agent will follow. Generated by Claude Opus 4.7 from a
                        session replay.
                    </p>
                    <div>
                        <label className="font-semibold">Assertions</label>
                        <p className="text-xs text-muted mb-2">
                            Extra checks the run must satisfy on top of the agent's own self-evaluation. Pulled from
                            PostHog data — events, logs, errors — not just what the browser shows.
                        </p>
                        <AssertionsEditor
                            assertions={testForm.assertions ?? []}
                            onAdd={addAssertion}
                            onUpdate={updateAssertion}
                            onRemove={removeAssertion}
                        />
                    </div>
                </div>
            </Form>
            {!isNew && (liveEvents.length > 0 || streaming) && (
                <section className="mt-8">
                    <div className="flex items-center justify-between mb-2">
                        <h3 className="font-semibold">Live run {streaming ? '(streaming…)' : ''}</h3>
                        <LemonButton type="tertiary" size="small" onClick={clearLiveEvents}>
                            Clear
                        </LemonButton>
                    </div>
                    <div
                        ref={liveLogRef}
                        className="border rounded p-2 max-h-96 overflow-auto bg-bg-light font-mono text-xs"
                    >
                        {liveEvents.map((ev, idx) => (
                            <div key={idx} className="py-0.5">
                                <span className="text-muted">[{ev.event}]</span>{' '}
                                {ev.data?.step != null && <span className="text-muted">step {ev.data.step} </span>}
                                {ev.event === 'tool_call' ? (
                                    <span>
                                        <strong>{ev.data.name}</strong>({JSON.stringify(ev.data.input ?? {})})
                                    </span>
                                ) : ev.event === 'tool_result' ? (
                                    <span className="text-muted">→ {String(ev.data.result).slice(0, 200)}</span>
                                ) : ev.event === 'model_text' ? (
                                    <span className="text-muted italic">{ev.data.text}</span>
                                ) : ev.event === 'status' ? (
                                    <span>
                                        {ev.data.message}{' '}
                                        {ev.data.replay_url && (
                                            <Link to={ev.data.replay_url} target="_blank">
                                                (replay)
                                            </Link>
                                        )}
                                    </span>
                                ) : ev.event === 'final' ? (
                                    <span>
                                        verdict: {ev.data.passed ? '✓ passed' : '✗ failed'} —{' '}
                                        {ev.data.output?.verdict?.reason ?? ev.data.error ?? ''}
                                    </span>
                                ) : (
                                    <span>{JSON.stringify(ev.data)}</span>
                                )}
                            </div>
                        ))}
                        {liveEvents.length === 0 && <div className="text-muted">Waiting for events…</div>}
                    </div>
                </section>
            )}
            {!isNew && (
                <section className="mt-8">
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
                        emptyState="No runs yet — hit Run to execute the prompt."
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
