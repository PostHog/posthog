import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconCheck, IconExternal, IconMinus, IconSparkles, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { useOpenAi } from '~/scenes/max/useOpenAi'
import { urls } from '~/scenes/urls'

import type { TestHogResultItemApi } from '../../generated/api.schemas'
import { HOG_EVAL_EXAMPLES } from '../hogEvalExamples'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { EvaluationTarget } from '../types'

const GLOBAL_NAME_CODE_CLASS = 'font-medium text-sm text-primary bg-fill-highlight-100 px-1.5 py-0.5 rounded'
const PROPERTY_NAME_CODE_CLASS = 'font-medium text-xs text-primary bg-fill-highlight-100 px-1 py-0.5 rounded'

type HogGlobalFieldType = 'string' | 'number' | 'object'
type HogGlobalDescription = string | Record<EvaluationTarget, string>

interface HogGlobalFieldDefinition {
    name: string
    type: HogGlobalFieldType
    description: HogGlobalDescription
}

interface HogGlobalDefinition {
    name: string
    collection: 'array' | 'object'
    description: HogGlobalDescription
    fields: readonly HogGlobalFieldDefinition[]
}

interface MonacoHogGlobalField {
    type: HogGlobalFieldType
    description: string
}

type MonacoHogGlobal = Record<string, MonacoHogGlobalField> | Record<string, MonacoHogGlobalField>[]

const HOG_EVAL_COMMON_GLOBAL_DEFINITIONS: readonly HogGlobalDefinition[] = [
    {
        name: 'evaluation_events',
        collection: 'array',
        description: {
            generation: 'The event for the generation being evaluated.',
            trace: 'Every event in the trace being evaluated.',
        },
        fields: [
            { name: 'uuid', type: 'string', description: 'The event UUID.' },
            { name: 'event', type: 'string', description: 'The PostHog event name.' },
            { name: 'timestamp', type: 'string', description: 'When the event was captured.' },
            { name: 'input', type: 'string', description: 'The raw input serialized as a string.' },
            { name: 'output', type: 'string', description: 'The raw output serialized as a string.' },
            {
                name: 'input_text',
                type: 'string',
                description: 'Best-effort readable text extracted from the input.',
            },
            {
                name: 'output_text',
                type: 'string',
                description: 'Best-effort readable text extracted from the output.',
            },
            {
                name: 'properties',
                type: 'object',
                description: 'Event properties without large input, output, and tool payloads.',
            },
        ],
    },
    {
        name: 'target',
        collection: 'object',
        description: {
            generation: 'Details about the generation being evaluated.',
            trace: 'Details about the trace being evaluated.',
        },
        fields: [
            {
                name: 'type',
                type: 'string',
                description: {
                    generation: 'The target type: generation.',
                    trace: 'The target type: trace.',
                },
            },
            {
                name: 'id',
                type: 'string',
                description: {
                    generation: 'The generation event UUID.',
                    trace: 'The trace ID.',
                },
            },
            {
                name: 'total_cost_usd',
                type: 'number',
                description: {
                    generation: 'The total cost for the generation in USD, when available.',
                    trace: 'The total cost for the trace in USD, when available.',
                },
            },
            {
                name: 'total_latency_seconds',
                type: 'number',
                description: {
                    generation: 'The total latency for the generation in seconds, when available.',
                    trace: 'The total latency for the trace in seconds, when available.',
                },
            },
        ],
    },
]

function resolveHogGlobalDescription(description: HogGlobalDescription, target: EvaluationTarget): string {
    return typeof description === 'string' ? description : description[target]
}

function buildMonacoHogGlobals(target: EvaluationTarget): Record<string, MonacoHogGlobal> {
    return Object.fromEntries(
        HOG_EVAL_COMMON_GLOBAL_DEFINITIONS.map((globalDefinition) => {
            const fields = Object.fromEntries(
                globalDefinition.fields.map((field) => [
                    field.name,
                    {
                        type: field.type,
                        description: resolveHogGlobalDescription(field.description, target),
                    },
                ])
            ) as Record<string, MonacoHogGlobalField>

            return [globalDefinition.name, globalDefinition.collection === 'array' ? [fields] : fields]
        })
    ) as Record<string, MonacoHogGlobal>
}

const HOG_EVAL_COMMON_GLOBALS_BY_TARGET = {
    generation: buildMonacoHogGlobals('generation'),
    trace: buildMonacoHogGlobals('trace'),
}

const HOG_EVAL_GLOBALS_BY_TARGET = {
    generation: {
        ...HOG_EVAL_COMMON_GLOBALS_BY_TARGET.generation,
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
        ...HOG_EVAL_COMMON_GLOBALS_BY_TARGET.trace,
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
            <LemonTable<TestHogResultItemApi>
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
                        render: (_, row) => {
                            if (!row.trace_id) {
                                return null
                            }
                            const isTrace = row.sample_type === 'trace'
                            return (
                                <Tooltip title={isTrace ? 'View trace' : 'View generation'}>
                                    <Link
                                        to={urls.aiObservabilityTrace(
                                            row.trace_id,
                                            isTrace || !row.event_uuid ? undefined : { event: row.event_uuid }
                                        )}
                                        target="_blank"
                                    >
                                        <IconExternal className="text-muted text-base" />
                                    </Link>
                                </Tooltip>
                            )
                        },
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
                rowKey="sample_id"
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
                                    ? 'Compile and run your code against up to 5 recent traces, the same way it runs online'
                                    : 'Compile and run your code against up to 5 recent generations matching your trigger filters'
                            }
                        >
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                loading={hogTestResultsLoading}
                                disabled={!source.trim()}
                                onClick={() => testHogOnSample()}
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
                <dl className="grid grid-cols-[max-content_minmax(0,1fr)] items-start gap-x-3 gap-y-2 text-sm text-muted">
                    {HOG_EVAL_COMMON_GLOBAL_DEFINITIONS.map((globalDefinition) => (
                        <Fragment key={globalDefinition.name}>
                            <dt>
                                <code className={GLOBAL_NAME_CODE_CLASS}>{globalDefinition.name}</code>
                            </dt>
                            <dd className="m-0">
                                <p className="m-0">
                                    {resolveHogGlobalDescription(globalDefinition.description, evaluation.target)}
                                </p>
                                <dl className="grid grid-cols-[max-content_minmax(0,1fr)] items-baseline gap-x-2 gap-y-1 mt-1.5">
                                    {globalDefinition.fields.map((field) => (
                                        <Fragment key={field.name}>
                                            <dt>
                                                <code className={PROPERTY_NAME_CODE_CLASS}>{field.name}</code>
                                            </dt>
                                            <dd className="m-0">
                                                {resolveHogGlobalDescription(field.description, evaluation.target)}
                                            </dd>
                                        </Fragment>
                                    ))}
                                </dl>
                            </dd>
                        </Fragment>
                    ))}
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
