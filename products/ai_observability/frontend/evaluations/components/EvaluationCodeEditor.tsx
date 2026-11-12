import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconChevronDown, IconExternal, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { autoRunMaxPrompt } from 'scenes/max/maxPrompt'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { evaluationIsDetector } from '../constants'
import { HOG_ADAPT_PROMPT, HogSnippet, hogAdaptContext, hogSnippetsFor } from '../evaluationSnippets'
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
            session: 'Every event in every trace in the session being evaluated, in order.',
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
            session: 'Details about the session being evaluated.',
        },
        fields: [
            {
                name: 'type',
                type: 'string',
                description: {
                    generation: 'The target type: generation.',
                    trace: 'The target type: trace.',
                    session: 'The target type: session.',
                },
            },
            {
                name: 'id',
                type: 'string',
                description: {
                    generation: 'The generation event UUID.',
                    trace: 'The trace ID.',
                    session: 'The session ID.',
                },
            },
            {
                name: 'total_cost_usd',
                type: 'number',
                description: {
                    generation: 'The total cost for the generation in USD, when available.',
                    trace: 'The total cost for the trace in USD, when available.',
                    session: 'The total cost across every trace in the session in USD, when available.',
                },
            },
            {
                name: 'total_latency_seconds',
                type: 'number',
                description: {
                    generation: 'The total latency for the generation in seconds, when available.',
                    trace: 'The total latency for the trace in seconds, when available.',
                    session:
                        'The latency of every trace in the session added up, in seconds. This is time spent on AI work, not how long the session lasted.',
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
    session: buildMonacoHogGlobals('session'),
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
    // No compatibility globals: those exist for Hog source saved before `target` and
    // `evaluation_events` landed, and no session-target source predates them. This mirrors
    // build_session_hog_globals, which builds the shared globals and nothing else.
    session: HOG_EVAL_COMMON_GLOBALS_BY_TARGET.session,
}

export function EvaluationCodeEditor(): JSX.Element {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setHogSource, setAllowsNA, setTrueIsFailure } = useActions(llmEvaluationLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    useAttachedContext(
        evaluation?.evaluation_type === 'hog' ? hogAdaptContext(evaluation, evaluation.evaluation_config.source) : null
    )

    if (!evaluation || evaluation.evaluation_type !== 'hog') {
        return <div>Loading...</div>
    }

    const source = evaluation.evaluation_config.source
    const trueIsFailure = evaluationIsDetector(evaluation)
    const { starters, templates } = hogSnippetsFor(evaluation)
    const snippetItem = (snippet: HogSnippet): LemonMenuItem => ({
        label: snippet.label,
        tooltip: snippet.allowsNA ? 'Also accepts a "doesn\'t apply" answer, for runs with no value.' : undefined,
        onClick: () => {
            if (snippet.allowsNA) {
                setAllowsNA(true)
            }
            // A detector template returns true for the problem, so its polarity comes with its code.
            if (snippet.trueIsFailure !== undefined && evaluation.output_type === 'boolean') {
                setTrueIsFailure(snippet.trueIsFailure)
            }
            setHogSource(snippet.source)
        },
    })

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
                <div className="flex flex-wrap gap-2 justify-between items-center text-sm text-muted">
                    <div className="flex items-center gap-2">
                        <LemonMenu
                            items={[
                                { title: 'Starters', items: starters.map(snippetItem) },
                                ...(templates.length > 0
                                    ? [{ title: 'From templates', items: templates.map(snippetItem) }]
                                    : []),
                            ]}
                        >
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                sideIcon={<IconChevronDown />}
                                disabledReason={
                                    starters.length + templates.length === 0
                                        ? 'Add a category first, then insert an example that returns it.'
                                        : undefined
                                }
                                data-attr="llma-evaluation-hog-insert-example"
                            >
                                Insert an example
                            </LemonButton>
                        </LemonMenu>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconSparkles />}
                            onClick={() => openSidePanel(SidePanelTab.Max, autoRunMaxPrompt(HOG_ADAPT_PROMPT))}
                            data-attr="llma-evaluation-hog-adapt-with-ai"
                        >
                            Adapt with PostHog AI
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-2">
                        <span>Expected output:</span>
                        <LemonTag type="completion">
                            {evaluation.output_type === 'categorical'
                                ? evaluation.output_config.allows_na
                                    ? 'Category keys or null'
                                    : 'Category keys'
                                : evaluation.output_type === 'numeric'
                                  ? evaluation.output_config.allows_na
                                      ? 'Number or null'
                                      : 'Number'
                                  : evaluation.output_config.allows_na
                                    ? 'Boolean or null (true/false/null)'
                                    : 'Boolean (true/false)'}
                        </LemonTag>
                    </div>
                </div>
            </div>

            {/* Folded by default, so the editor stays close to the rest of the form. */}
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'reference',
                        header: 'Hog reference',
                        dataAttr: 'llma-evaluation-hog-reference',
                        content: (
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <h4 className="text-sm font-semibold m-0">Available globals</h4>
                                    <Link to="https://posthog.com/docs/hog" target="_blank" className="text-sm">
                                        Hog language reference <IconExternal className="inline text-xs" />
                                    </Link>
                                </div>
                                <dl className="grid grid-cols-[max-content_minmax(0,1fr)] items-start gap-x-3 gap-y-2 text-sm text-muted">
                                    {HOG_EVAL_COMMON_GLOBAL_DEFINITIONS.map((globalDefinition) => (
                                        <Fragment key={globalDefinition.name}>
                                            <dt>
                                                <code className={GLOBAL_NAME_CODE_CLASS}>{globalDefinition.name}</code>
                                            </dt>
                                            <dd className="m-0">
                                                <p className="m-0">
                                                    {resolveHogGlobalDescription(
                                                        globalDefinition.description,
                                                        evaluation.target
                                                    )}
                                                </p>
                                                <dl className="grid grid-cols-[max-content_minmax(0,1fr)] items-baseline gap-x-2 gap-y-1 mt-1.5">
                                                    {globalDefinition.fields.map((field) => (
                                                        <Fragment key={field.name}>
                                                            <dt>
                                                                <code className={PROPERTY_NAME_CODE_CLASS}>
                                                                    {field.name}
                                                                </code>
                                                            </dt>
                                                            <dd className="m-0">
                                                                {resolveHogGlobalDescription(
                                                                    field.description,
                                                                    evaluation.target
                                                                )}
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
                                        {evaluation.output_type === 'categorical' ? (
                                            <span>
                                                Return configured category keys in a list. An empty list is valid for
                                                multiple selection; null means N/A when allowed.
                                            </span>
                                        ) : evaluation.output_type === 'numeric' ? (
                                            <span>Return a number in the range you set.</span>
                                        ) : (
                                            <>
                                                Return <code>true</code> ({trueIsFailure ? 'fail' : 'pass'}) or{' '}
                                                <code>false</code> ({trueIsFailure ? 'pass' : 'fail'})
                                                {evaluation.output_config.allows_na ? (
                                                    <>
                                                        {' '}
                                                        or <code>null</code> (N/A)
                                                    </>
                                                ) : null}
                                            </>
                                        )}
                                    </li>
                                    {evaluation.output_config.allows_na && (
                                        <li>
                                            Return <code>null</code> when the check doesn't apply
                                        </li>
                                    )}
                                    <li>
                                        Use <code>print()</code> to add reasoning (visible in evaluation runs)
                                    </li>
                                </ul>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
