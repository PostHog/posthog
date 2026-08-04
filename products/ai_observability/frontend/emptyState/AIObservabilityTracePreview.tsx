import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'

interface PreviewGeneration {
    name: string
    model: string
    latency: string
    cost: string
    error?: boolean
}

// Example generations - hand-authored, not real data. Shaped like the traces tab's
// signature columns: span name, model, latency, cost.
const GENERATIONS: PreviewGeneration[] = [
    { name: 'support_reply', model: 'claude-sonnet-4', latency: '2.4s', cost: '$0.0132' },
    { name: 'summarize_thread', model: 'gpt-4.1-mini', latency: '0.8s', cost: '$0.0004' },
    { name: 'classify_intent', model: 'gpt-4.1-nano', latency: 'err', cost: '', error: true },
    { name: 'embed_docs', model: 'text-embedding-3-small', latency: '0.1s', cost: '$0.0001' },
    { name: 'generate_title', model: 'gemini-2.5-flash', latency: '0.5s', cost: '$0.0007' },
]

// A hand-authored series for the sparkline - abstract, just enough to read as a trend.
const SPARK = [7, 9, 8, 11, 10, 13, 12, 15, 13, 16, 15, 18]

function sparkPaths(): { line: string; area: string } {
    const width = 100
    const height = 40
    const pad = 3
    const min = Math.min(...SPARK)
    const max = Math.max(...SPARK)
    const points = SPARK.map((value, i) => {
        const x = (i / (SPARK.length - 1)) * width
        const y = height - pad - ((value - min) / (max - min || 1)) * (height - 2 * pad)
        return `${x.toFixed(1)} ${y.toFixed(1)}`
    })
    const line = 'M ' + points.join(' L ')
    return { line, area: `${line} L ${width} ${height} L 0 ${height} Z` }
}

/**
 * Example-data preview for the AI observability empty state: a generations list plus
 * a cost tile - static rows, no timers, per the preview rules in the
 * `building-product-empty-states` skill.
 */
export function AIObservabilityTracePreview({ mode }: { mode: ProductEmptyStateMode }): JSX.Element {
    const { line, area } = sparkPaths()

    return (
        <div className="flex flex-col gap-3">
            <div className="rounded-md border border-primary bg-surface-primary p-3">
                <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-semibold">Generations</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                {mode === 'waiting-for-data' ? (
                    <div className="mb-1 flex items-center gap-2 rounded border border-dashed border-primary px-2 py-1.5 text-xs text-secondary">
                        <Spinner className="text-sm" />
                        Listening for your first generation…
                    </div>
                ) : null}

                <div className="flex flex-col">
                    {GENERATIONS.map((generation, i) => (
                        <div
                            key={i}
                            className={cn(
                                'flex items-center gap-2 border-b border-primary px-1 py-1.5 text-xs last:border-b-0',
                                generation.error && 'text-danger'
                            )}
                        >
                            <span className="font-mono font-medium">{generation.name}</span>
                            <LemonTag size="small" type={generation.error ? 'danger' : 'muted'}>
                                {generation.model}
                            </LemonTag>
                            <span className="ml-auto shrink-0 text-secondary tabular-nums">{generation.latency}</span>
                            <span className="w-14 shrink-0 text-right text-secondary tabular-nums">
                                {generation.cost}
                            </span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="rounded-md border border-primary bg-surface-primary p-3">
                <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs font-semibold">LLM costs · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="mb-2 text-2xl font-bold tabular-nums">
                    $128.40
                    <span className="ml-2 align-middle text-xs font-semibold text-secondary">▲ 12%</span>
                </div>

                <svg className="h-10 w-full" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
                    <path d={area} fill="var(--empty-state-accent)" opacity={0.15} />
                    <path
                        d={line}
                        fill="none"
                        stroke="var(--empty-state-accent)"
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
            </div>
        </div>
    )
}
