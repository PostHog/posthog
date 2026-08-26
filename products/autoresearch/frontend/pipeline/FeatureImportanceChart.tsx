import { LemonCollapse, Tooltip } from '@posthog/lemon-ui'

interface FeatureImportance {
    name: string
    direction?: string
    importance?: number
    note?: string
}

/** Pull the typed top-features list + note out of the loosely-typed model_explanation JSON. */
function parseExplanation(explanation: unknown): { features: FeatureImportance[]; note: string | null } {
    if (!explanation || typeof explanation !== 'object') {
        return { features: [], note: null }
    }
    const obj = explanation as { top_features?: unknown; note?: unknown }
    const note = typeof obj.note === 'string' ? obj.note : null
    const raw = Array.isArray(obj.top_features) ? obj.top_features : []
    const features = raw
        .map((f): FeatureImportance | null => {
            if (!f || typeof f !== 'object') {
                return null
            }
            const { name, direction, importance, note: featureNote } = f as Record<string, unknown>
            if (typeof name !== 'string') {
                return null
            }
            return {
                name,
                direction: typeof direction === 'string' ? direction : undefined,
                importance: typeof importance === 'number' ? importance : undefined,
                note: typeof featureNote === 'string' ? featureNote : undefined,
            }
        })
        .filter((f): f is FeatureImportance => f !== null)
    // The agent already lists features strongest-first; only re-rank when it gave numbers.
    if (features.some((f) => f.importance != null)) {
        features.sort((a, b) => (b.importance ?? 0) - (a.importance ?? 0))
    }
    return { features, note }
}

/**
 * A model's top feature drivers: importance bars when the agent supplied numeric
 * importances, otherwise a ranked list with the agent's per-feature notes.
 */
export function FeatureImportanceChart({ explanation }: { explanation: unknown }): JSX.Element | null {
    const { features, note } = parseExplanation(explanation)
    if (features.length === 0) {
        return null
    }
    const hasImportances = features.some((f) => f.importance != null)
    const content = (
        <div className="space-y-2">
            <div className="text-xs text-muted">
                <span style={{ color: 'var(--success)' }}>● raises</span>{' '}
                <span style={{ color: 'var(--danger)' }}>● lowers</span> the prediction
                {hasImportances ? ' · bars on a fixed 0-1 importance scale' : ' · strongest first'}
            </div>
            <div className="space-y-1">
                {features.map((f) => {
                    const isNegative = f.direction === 'negative'
                    return (
                        <div key={f.name} className="flex items-center gap-2 text-sm">
                            <div className="w-48 shrink-0 truncate font-mono text-xs" title={f.name}>
                                <span style={{ color: isNegative ? 'var(--danger)' : 'var(--success)' }}>● </span>
                                {f.name}
                            </div>
                            {hasImportances ? (
                                <div
                                    className="flex-1 rounded h-4 overflow-hidden"
                                    style={{ backgroundColor: 'var(--border)' }}
                                >
                                    <Tooltip
                                        title={`${isNegative ? 'Lowers' : 'Raises'} the prediction · importance ${(f.importance ?? 0).toFixed(3)}`}
                                    >
                                        <div
                                            className="h-full rounded"
                                            style={{
                                                width: `${Math.min(100, Math.max(2, (f.importance ?? 0) * 100))}%`,
                                                backgroundColor: isNegative ? 'var(--danger)' : 'var(--success)',
                                            }}
                                        />
                                    </Tooltip>
                                </div>
                            ) : (
                                <Tooltip title={f.note}>
                                    <div className="flex-1 min-w-0 truncate text-xs text-muted">{f.note}</div>
                                </Tooltip>
                            )}
                        </div>
                    )
                })}
            </div>
            {note && <div className="text-xs text-muted italic">{note}</div>}
        </div>
    )
    return (
        <LemonCollapse
            size="small"
            defaultActiveKey="features"
            panels={[{ key: 'features', header: 'Top feature drivers', content }]}
        />
    )
}
