import { LemonTag } from '@posthog/lemon-ui'

import { AutoresearchIterationStatusEnumApi, IterationTrailApi } from '../generated/api.schemas'

const ITERATION_STATUS: Record<
    AutoresearchIterationStatusEnumApi,
    { type: 'success' | 'default' | 'danger'; label: string }
> = {
    kept: { type: 'success', label: 'Kept' },
    discarded: { type: 'default', label: 'Discarded' },
    crashed: { type: 'danger', label: 'Crashed' },
}

/** Render the agent's model_spec (class + hyperparameters) compactly. random_state is noise — drop it. */
function formatModelSpec(spec: unknown): { className: string; params: string } | null {
    if (!spec || typeof spec !== 'object') {
        return null
    }
    const { model_class, model_params } = spec as { model_class?: string; model_params?: Record<string, unknown> }
    const className = (model_class ?? '').split('.').pop() ?? ''
    const params = model_params
        ? Object.entries(model_params)
              .filter(([key]) => key !== 'random_state')
              .map(([key, value]) => `${key}=${value}`)
              .join(', ')
        : ''
    return className || params ? { className, params } : null
}

/** The per-iteration breakdown for one training run: what the agent tried each step and whether it stuck. */
export function IterationTrail({ iterations }: { iterations: readonly IterationTrailApi[] }): JSX.Element {
    if (iterations.length === 0) {
        return <div className="text-muted text-sm">No iteration details were recorded for this run.</div>
    }
    const bestHoldout = Math.max(...iterations.map((it) => it.holdout_score ?? -Infinity))
    return (
        <div className="space-y-2">
            {iterations.map((it) => {
                const spec = formatModelSpec(it.model_spec)
                const tag = ITERATION_STATUS[it.status]
                const isBest = it.holdout_score != null && it.holdout_score === bestHoldout
                return (
                    <div key={it.iteration_number} className="border rounded p-2">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-semibold">Iteration {it.iteration_number}</span>
                                <LemonTag type={tag.type} size="small">
                                    {tag.label}
                                </LemonTag>
                                {isBest && (
                                    <LemonTag type="completion" size="small">
                                        Best
                                    </LemonTag>
                                )}
                            </div>
                            <div className="text-xs text-muted flex items-center gap-3">
                                <span>
                                    Holdout AUC{' '}
                                    <span className="font-semibold text-default">
                                        {it.holdout_score != null ? it.holdout_score.toFixed(4) : '—'}
                                    </span>
                                </span>
                                {it.train_score != null && <span>Train {it.train_score.toFixed(4)}</span>}
                            </div>
                        </div>
                        {spec && (
                            <div className="text-xs text-muted font-mono mt-1">
                                {spec.className}
                                {spec.params && ` · ${spec.params}`}
                            </div>
                        )}
                        {it.agent_description && (
                            <div className="text-sm text-default mt-1">{it.agent_description}</div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
