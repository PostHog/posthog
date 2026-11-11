import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { TraceNodeApi } from '../../generated/api.schemas'
import { NodeKindGlyph } from '../../redesign/trace/components/NodeKindGlyph'
import { NodeStatsLine } from '../../redesign/trace/components/NodeStatsLine'
import type { EvaluationTarget } from '../types'

const stats = (costUsd: number | null, latencyMs: number): TraceNodeApi['stats'] => ({
    costUsd,
    latencyMs,
    inputTokens: null,
    outputTokens: null,
    cacheReadTokens: null,
    cacheWriteTokens: null,
})

const node = (
    id: string,
    kind: TraceNodeApi['kind'],
    name: string,
    nodeStats: TraceNodeApi['stats'],
    children: TraceNodeApi[] = [],
    model: string | null = null
): TraceNodeApi => ({ id, kind, name, label: name, model, stats: nodeStats, hasError: false, children })

const SAMPLE_SESSION: TraceNodeApi[] = [
    node('trace-1', 'trace', 'support_chat', stats(0.0041, 2300), [
        node('span-1', 'span', 'search_docs', stats(null, 400)),
        node('gen-1', 'generation', 'answer_question', stats(0.0032, 1600), [], 'gpt-4.1-mini'),
    ]),
    node('trace-2', 'trace', 'support_chat', stats(0.0028, 1400), [
        node('gen-3', 'generation', 'answer_question', stats(0.0028, 1400), [], 'gpt-4.1-mini'),
    ]),
]

const HIGHLIGHT = 'rounded bg-accent-highlight-light ring-1 ring-accent'

function RunLabel(): JSX.Element {
    return <span className="ml-auto shrink-0 pl-2 text-xs font-semibold text-accent">1 run</span>
}

function Row({ item, depth, oneRun }: { item: TraceNodeApi; depth: number; oneRun: boolean }): JSX.Element {
    return (
        <div
            // Same indent as the trace view's tree rows.
            className={cn(
                'flex min-w-0 items-center gap-2 py-0.5 pr-1.5',
                depth === 0 ? 'pl-1.5' : 'pl-4.5',
                oneRun && HIGHLIGHT
            )}
        >
            <NodeKindGlyph kind={item.kind} />
            <span className="truncate text-xs font-medium">{item.name}</span>
            <NodeStatsLine stats={item.stats} model={item.model} compact className="min-w-0" />
            {oneRun && <RunLabel />}
        </div>
    )
}

export function EvaluationLevelDiagram({ level }: { level: EvaluationTarget }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div
                aria-hidden
                className={cn(
                    'flex flex-col gap-0.5 rounded border border-primary bg-surface-primary p-1',
                    level === 'session' && HIGHLIGHT
                )}
            >
                <div className="flex items-center px-1.5 py-0.5 text-xs text-secondary">
                    Example session
                    {level === 'session' && <RunLabel />}
                </div>
                {SAMPLE_SESSION.map((trace, traceIndex) => {
                    const traceIsRun = level === 'trace' && traceIndex === 0
                    return (
                        <div key={trace.id} className={cn(traceIsRun && HIGHLIGHT)}>
                            <div className="flex items-center">
                                <div className="min-w-0 flex-1">
                                    <Row item={trace} depth={0} oneRun={false} />
                                </div>
                                {traceIsRun && (
                                    <span className="pr-1.5">
                                        <RunLabel />
                                    </span>
                                )}
                            </div>
                            {trace.children.map((child) => (
                                <Row
                                    key={child.id}
                                    item={child}
                                    depth={1}
                                    oneRun={level === 'generation' && child.id === 'gen-1'}
                                />
                            ))}
                        </div>
                    )
                })}
            </div>
            <span className="text-xs text-secondary">
                Learn about{' '}
                <Link to="https://posthog.com/docs/ai-observability/traces" target="_blank">
                    traces
                </Link>{' '}
                and{' '}
                <Link to="https://posthog.com/docs/ai-observability/sessions" target="_blank">
                    sessions
                </Link>
                .
            </span>
        </div>
    )
}
