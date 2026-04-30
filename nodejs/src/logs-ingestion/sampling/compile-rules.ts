import type { CompiledRuleSet, CompiledSamplingRule, SeverityAction } from './evaluate'

export type SamplingRuleRow = {
    id: string
    rule_type: string
    scope_service: string | null
    scope_path_pattern: string | null
    scope_attribute_filters: unknown
    config: Record<string, unknown>
    /** Row version from DB; used by cache watermark only, ignored by compileRuleSet. */
    version?: number
}

const defaultSeverityActions = (): [SeverityAction, SeverityAction, SeverityAction, SeverityAction] => [
    { type: 'keep' },
    { type: 'keep' },
    { type: 'keep' },
    { type: 'keep' },
]

function parseSeverityActions(raw: unknown): [SeverityAction, SeverityAction, SeverityAction, SeverityAction] {
    const out = defaultSeverityActions()
    if (!raw || typeof raw !== 'object') {
        return out
    }
    const actions = (raw as { actions?: Record<string, unknown> }).actions
    if (!actions || typeof actions !== 'object') {
        return out
    }
    const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR'] as const
    for (let i = 0; i < levels.length; i++) {
        const key = levels[i]
        const a = actions[key] as Record<string, unknown> | undefined
        if (!a || typeof a.type !== 'string') {
            continue
        }
        if (a.type === 'drop') {
            out[i] = { type: 'drop' }
        } else if (a.type === 'sample' && typeof a.rate === 'number') {
            out[i] = { type: 'sample', rate: Math.max(0, Math.min(1, a.rate)) }
        } else {
            out[i] = { type: 'keep' }
        }
    }
    return out
}

function parseAlwaysKeep(config: Record<string, unknown>): CompiledSamplingRule['alwaysKeep'] {
    const ak = config.always_keep as Record<string, unknown> | undefined
    if (!ak || typeof ak !== 'object') {
        return null
    }
    const statusGte = typeof ak.status_gte === 'number' ? ak.status_gte : null
    const latencyMsGt = typeof ak.latency_ms_gt === 'number' ? ak.latency_ms_gt : null
    const preds = Array.isArray(ak.attribute_predicates) ? (ak.attribute_predicates as any[]) : []
    const attributePredicates = preds
        .filter((p) => p && typeof p.key === 'string' && typeof p.op === 'string')
        .map((p) => ({
            key: p.key as string,
            op: p.op as string,
            value: typeof p.value === 'string' ? p.value : undefined,
        }))
    if (statusGte == null && latencyMsGt == null && attributePredicates.length === 0) {
        return null
    }
    return { statusGte, latencyMsGt, attributePredicates }
}

export function compileRuleSet(rows: SamplingRuleRow[]): CompiledRuleSet {
    const rules: CompiledSamplingRule[] = []
    for (const row of rows) {
        let pathRegex: RegExp | null = null
        if (row.scope_path_pattern) {
            try {
                pathRegex = new RegExp(row.scope_path_pattern)
            } catch {
                pathRegex = /^$/
            }
        }
        let pathDropPatterns: RegExp[] | null = null
        if (row.rule_type === 'path_drop') {
            const patterns = (row.config.patterns as unknown[]) || []
            pathDropPatterns = []
            for (const p of patterns) {
                if (typeof p !== 'string') {
                    continue
                }
                try {
                    pathDropPatterns.push(new RegExp(p))
                } catch {
                    /* skip invalid */
                }
            }
        }
        const rt = row.rule_type as CompiledSamplingRule['ruleType']
        rules.push({
            id: row.id,
            ruleType: rt === 'path_drop' || rt === 'rate_limit' || rt === 'severity_sampling' ? rt : 'path_drop',
            scopeService: row.scope_service,
            pathRegex,
            pathDropPatterns,
            severityActions: parseSeverityActions(row.config),
            alwaysKeep: parseAlwaysKeep(row.config),
        })
    }
    return { rules }
}
