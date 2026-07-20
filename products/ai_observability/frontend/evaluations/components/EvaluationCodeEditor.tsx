import { useActions, useValues } from 'kea'

import { IconCheck, IconExternal, IconMinus, IconSparkles, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { useOpenAi } from '~/scenes/max/useOpenAi'
import { urls } from '~/scenes/urls'

import { HOG_EVAL_EXAMPLES } from '../hogEvalExamples'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { HogTestResult } from '../types'

const HOG_EVAL_COMMON_GLOBALS = {
    evaluation_events: [
        {
            uuid: { type: 'string' },
            event: { type: 'string' },
            timestamp: { type: 'string' },
            input: { type: 'string' },
            output: { type: 'string' },
            input_text: { type: 'string', description: 'Best-effort readable input text' },
            output_text: { type: 'string', description: 'Best-effort readable output text' },
            properties: { type: 'object' },
        },
    ],
    target: {
        type: { type: 'string', description: 'generation or trace' },
        id: { type: 'string' },
        total_cost_usd: { type: 'number' },
        total_latency_seconds: { type: 'number' },
    },
}

const HOG_EVAL_GLOBALS_BY_TARGET = {
    generation: {
        ...HOG_EVAL_COMMON_GLOBALS,
        // Compatibility globals kept for saved generation Hog source.
        input: { type: 'string', description: 'The input to the LLM' },
        output: { type: 'string', description: 'The output from the LLM' },
        properties: { type: 'object', description: 'All event properties' },
        event: {
            uuid: { type: 'string' },
            event: { type: 'string' },
            distinct_id: { type: 'string' },
        },
    },
    trace: {
        ...HOG_EVAL_COMMON_GLOBALS,
        // Compatibility globals kept for saved trace Hog source.
        events: [
            {
                uuid: { type: 'string' },
                event: { type: 'string' },
                timestamp: { type: 'string' },
                input: { type: 'string' },
                output: { type: 'string' },
                properties: { type: 'object' },
            },
        ],
        trace: {
            id: { type: 'string' },
            event_count: { type: 'number' },
        },
    },
}

function HogTestResultsPanel(): JSX.Element | null {
    const { hogTestResults, hogTestResultsLoading } = useValues(llmEvaluationLogic)
    const { clearHogTestResults } = useActions(llmEvaluationLogic)

    if (!hogTestResults && !hogTestResultsLoading) {
        return null
    }

    const passed = hogTestResults?.filter((r) => r.result === true).length ?? 0
    const failed = hogTestResults?.filter((r) => r.result === false).length ?? 0
    const na = hogTestResults?.filter((r) => r.result === null && !r.error).length ?? 0
    const errors = hogTestResults?.filter((r) => r.error !== null).length ?? 0

    return (
        <div className="border rounded p-3 space-y-2">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 text-sm">
                    <span className="font-semibold">Test results</span>
                    {hogTestResults && (
                        <>
                            <LemonTag type="success" icon={<IconCheck />}>
                                {passed} passed
                            </LemonTag>
                            <LemonTag type="danger" icon={<IconX />}>
                                {failed} failed
                            </LemonTag>
                            {na > 0 && (
                                <LemonTag type="muted" icon={<IconMinus />}>
                                    {na} N/A
                                </LemonTag>
                            )}
                            {errors > 0 && (
                                <LemonTag type="danger" icon={<IconWarning />}>
                                    {errors} errors
                                </LemonTag>
                            )}
                        </>
                    )}
                </div>
                <LemonButton type="secondary" size="xsmall" onClick={clearHogTestResults}>
                    Clear
                </LemonButton>
            </div>
            <LemonTable<HogTestResult>
                columns={[
                    {
                        title: 'Result',
                        key: 'result',
                        width: 100,
                        render: (_, row) => {
                            if (row.error) {
                                return (
                                    <Tooltip title={row.error}>
                                        <span>
                                            <LemonTag type="danger" icon={<IconWarning />}>
                                                Error
                                            </LemonTag>
                                        </span>
                                    </Tooltip>
                                )
                            }
                            if (row.result === null) {
                                return (
                                    <LemonTag type="muted" icon={<IconMinus />}>
                                        N/A
                                    </LemonTag>
                                )
                            }
                            return row.result ? (
                                <LemonTag type="success" icon={<IconCheck />}>
                                    Pass
                                </LemonTag>
                            ) : (
                                <LemonTag type="danger" icon={<IconX />}>
                                    Fail
                                </LemonTag>
                            )
                        },
                    },
                    {
                        title: 'Reasoning',
                        key: 'reasoning',
                        render: (_, row) => (
                            <div className="truncate text-sm">
                                {row.reasoning || row.error || <span className="text-muted italic">none</span>}
                            </div>
                        ),
                    },
                    {
                        title: '',
                        key: 'link',
                        width: 32,
                        render: (_, row) =>
                            row.trace_id ? (
                                <Tooltip title="View generation">
                                    <Link
                                        to={urls.aiObservabilityTrace(row.trace_id, {
                                            event: row.event_uuid,
                                        })}
                                        target="_blank"
                                    >
                                        <IconExternal className="text-muted text-base" />
                                    </Link>
                                </Tooltip>
                            ) : null,
                    },
                ]}
                expandable={{
                    expandedRowRender: (row) => (
                        <pre className="text-sm whitespace-pre-wrap m-0 p-2">
                            {row.reasoning || row.error || 'No output'}
                        </pre>
                    ),
                    rowExpandable: (row) => !!(row.reasoning || row.error),
                }}
                dataSource={hogTestResults ?? []}
                loading={hogTestResultsLoading}
                rowKey="event_uuid"
                size="small"
            />
        </div>
    )
}

export function EvaluationCodeEditor(): JSX.Element {
    const { evaluation, hogTestResultsLoading } = useValues(llmEvaluationLogic)
    const { setHogSource, testHogOnSample } = useActions(llmEvaluationLogic)
    const { openAi } = useOpenAi()

    if (!evaluation || evaluation.evaluation_type !== 'hog') {
        return <div>Loading...</div>
    }

    const source = evaluation.evaluation_config.source

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <CodeEditorResizeable
                    language="hog"
                    value={source}
                    onChange={(v) => setHogSource(v ?? '')}
                    globals={HOG_EVAL_GLOBALS_BY_TARGET[evaluation.target]}
                    minHeight="12rem"
                    maxHeight="60vh"
                    options={{
                        minimap: { enabled: false },
                        wordWrap: 'on',
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                        fixedOverflowWidgets: true,
                        suggest: { showInlineDetails: true },
                        quickSuggestionsDelay: 300,
                    }}
                />
                <div className="flex justify-between items-center text-sm text-muted">
                    <div className="flex items-center gap-2">
                        <Tooltip
                            title={
                                evaluation.target === 'trace'
                                    ? 'Preview this code against up to 5 recent generations. Online runs evaluate the whole trace.'
                                    : 'Compile and run your code against up to 5 recent generations matching your trigger filters'
                            }
                        >
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                loading={hogTestResultsLoading}
                                disabled={!source.trim()}
                                onClick={testHogOnSample}
                                data-attr="llma-evaluation-test-hog"
                            >
                                Test on sample
                            </LemonButton>
                        </Tooltip>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconSparkles />}
                            onClick={() =>
                                openAi('Help me write Hog evaluation code for this evaluation', {
                                    evaluation: {
                                        id: evaluation.id,
                                        name: evaluation.name,
                                        description: evaluation.description,
                                        evaluation_type: evaluation.evaluation_type,
                                        hog_source: evaluation.evaluation_config.source,
                                    },
                                })
                            }
                            data-attr="llma-evaluation-generate-with-ai"
                        >
                            Generate with AI
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <span>Expected output:</span>
                        <LemonTag type="completion">
                            {evaluation.output_config.allows_na
                                ? 'Boolean or null (true/false/null)'
                                : 'Boolean (true/false)'}
                        </LemonTag>
                    </div>
                </div>
            </div>

            <HogTestResultsPanel />

            <div className="bg-bg-light border rounded p-3">
                <div className="flex items-center justify-between mb-2">
                    <div>
                        <h4 className="text-sm font-semibold m-0">Examples</h4>
                        <p className="text-xs text-muted m-0">Starter examples to play with</p>
                    </div>
                    <Link to="https://posthog.com/docs/hog" target="_blank" className="text-sm">
                        Hog language reference <IconExternal className="inline text-xs" />
                    </Link>
                </div>
                <div className="flex flex-wrap gap-1.5 mb-3">
                    {HOG_EVAL_EXAMPLES.map((example) => (
                        <LemonButton
                            key={example.label}
                            type="secondary"
                            size="xsmall"
                            onClick={() => setHogSource(example.source)}
                        >
                            {example.label}
                        </LemonButton>
                    ))}
                </div>
                <h4 className="text-sm font-semibold mb-2">Available globals</h4>
                <dl className="grid grid-cols-[max-content_minmax(0,1fr)] items-baseline gap-x-3 gap-y-2 text-sm text-muted">
                    <dt>
                        <code>evaluation_events</code>
                    </dt>
                    <dd className="m-0">
                        <p className="m-0">One generation event, or every event in the trace.</p>
                        <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-2 gap-y-0.5 mt-1">
                            <dt>
                                <code>uuid</code>
                            </dt>
                            <dd className="m-0">The event UUID.</dd>
                            <dt>
                                <code>event</code>
                            </dt>
                            <dd className="m-0">The PostHog event name.</dd>
                            <dt>
                                <code>timestamp</code>
                            </dt>
                            <dd className="m-0">When the event was captured.</dd>
                            <dt>
                                <code>input</code>
                            </dt>
                            <dd className="m-0">The raw input serialized as a string.</dd>
                            <dt>
                                <code>output</code>
                            </dt>
                            <dd className="m-0">The raw output serialized as a string.</dd>
                            <dt>
                                <code>input_text</code>
                            </dt>
                            <dd className="m-0">Readable text extracted from the input.</dd>
                            <dt>
                                <code>output_text</code>
                            </dt>
                            <dd className="m-0">Readable text extracted from the output.</dd>
                            <dt>
                                <code>properties</code>
                            </dt>
                            <dd className="m-0">Event properties without large input, output, and tool payloads.</dd>
                        </dl>
                    </dd>
                    <dt>
                        <code>target</code>
                    </dt>
                    <dd className="m-0">
                        <p className="m-0">Details about the generation or trace being evaluated.</p>
                        <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-2 gap-y-0.5 mt-1">
                            <dt>
                                <code>type</code>
                            </dt>
                            <dd className="m-0">
                                <code>generation</code> or <code>trace</code>.
                            </dd>
                            <dt>
                                <code>id</code>
                            </dt>
                            <dd className="m-0">The event UUID or trace ID.</dd>
                            <dt>
                                <code>total_cost_usd</code>
                            </dt>
                            <dd className="m-0">The total cost in USD, when available.</dd>
                            <dt>
                                <code>total_latency_seconds</code>
                            </dt>
                            <dd className="m-0">The total latency in seconds, when available.</dd>
                        </dl>
                    </dd>
                </dl>
                <h4 className="text-sm font-semibold mt-3 mb-2">Tips</h4>
                <ul className="text-sm text-muted space-y-1 list-disc list-inside">
                    <li>
                        Return <code>true</code> (pass) or <code>false</code> (fail)
                        {evaluation.output_config.allows_na ? (
                            <>
                                {' '}
                                or <code>null</code> (N/A)
                            </>
                        ) : null}
                    </li>
                    {evaluation.output_config.allows_na && (
                        <li>
                            Return <code>null</code> when the evaluation criteria doesn't apply
                        </li>
                    )}
                    <li>
                        Use <code>print()</code> to add reasoning (visible in evaluation runs)
                    </li>
                </ul>
            </div>
        </div>
    )
}
